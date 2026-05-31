// scripts/seed.js
// Seeds Supabase from scraper output files.
// Prerequisites: run scrapers first, then: node scripts/seed.js

require("dotenv").config({ path: ".env.local" });
const fs = require("fs");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
);

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseFeeCents(raw) {
  if (raw === null || raw === undefined) return null;
  const str = String(raw);
  if (/free|gratuit/i.test(str)) return 0;
  const match = str.match(/(\d+)[.,](\d{2})/);
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2]);
  const whole = str.match(/(\d+)/);
  if (whole) return parseInt(whole[1]) * 100;
  return null;
}

function centsToLabel(cents) {
  if (cents === null || cents === undefined) return null;
  if (cents === 0) return "Free";
  return `€${(cents / 100).toFixed(2)}`;
}

function parseEta(raw) {
  if (!raw) return { min: null, max: null, label: null };
  const range = raw.match(/(\d+)\s*(?:à|to|-|–)\s*(\d+)/);
  if (range) {
    const min = parseInt(range[1]);
    const max = parseInt(range[2]);
    return {
      min,
      max,
      label: min === max ? `${min} min` : `${min}–${max} min`,
    };
  }
  const single = raw.match(/(\d+)\s*min/i);
  if (single) {
    const v = parseInt(single[1]);
    return { min: v, max: v, label: `${v} min` };
  }
  return { min: null, max: null, label: raw };
}

function priceToCents(raw) {
  if (raw === null || raw === undefined) return null;
  const str = String(raw);
  if (/free|gratuit/i.test(str)) return 0;
  const match = str.match(/(\d+)[.,](\d{2})/);
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2]);
  return null;
}

// ── Platform seeder ───────────────────────────────────────────────────────────

async function seedPlatform({ dbPlatform, dataFile }) {
  // Look in parent directory (food-price-compare/) for output files
  const filePath = path.join(__dirname, "..", "..", dataFile);
  if (!fs.existsSync(filePath)) {
    console.log(`⏭  ${dataFile} not found — skipping ${dbPlatform}`);
    return;
  }

  const raw = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  const restaurants = Array.isArray(raw) ? raw : [raw];
  console.log(`\n📥 ${dbPlatform}: ${restaurants.length} restaurant(s)`);

  for (const r of restaurants) {
    const name = r.name || r.restaurantName || r.title;
    if (!name) continue;

    // Upsert restaurant
    const { data: restaurant, error: rErr } = await supabase
      .from("restaurants")
      .upsert({ name, city: "Brussels" }, { onConflict: "name,city" })
      .select()
      .single();

    if (rErr) {
      console.error(`  ❌ ${name} restaurant:`, rErr.message);
      continue;
    }

    const feeCents = parseFeeCents(r.deliveryFee);
    const eta = parseEta(r.eta);

    // Upsert platform listing
    const { data: listing, error: lErr } = await supabase
      .from("platform_listings")
      .upsert(
        {
          restaurant_id: restaurant.id,
          platform: dbPlatform,
          platform_url: r.url ?? r.restaurantUrl ?? null,
          delivery_fee_cents: feeCents,
          delivery_fee_label: centsToLabel(feeCents),
          eta_min: eta.min,
          eta_max: eta.max,
          eta_label: eta.label,
          rating:
            r.rating && r.rating !== "N/A"
              ? parseFloat(String(r.rating))
              : null,
          rating_count: r.reviewCount ?? null,
          hero_image_url: r.heroImage ?? r.imageUrl ?? null,
          scraped_at: new Date().toISOString(),
        },
        { onConflict: "restaurant_id,platform" },
      )
      .select()
      .single();

    if (lErr) {
      console.error(`  ❌ ${name} listing:`, lErr.message);
      continue;
    }

    // Refresh menu items
    await supabase.from("menu_items").delete().eq("listing_id", listing.id);

    const menuItems = r.menuItems ?? r.menu ?? [];
    if (menuItems.length > 0) {
      const rows = menuItems.map((item) => {
        const cents = priceToCents(item.price);
        return {
          listing_id: listing.id,
          name: item.name ?? "Unknown",
          description: item.description ?? null,
          price_cents: cents,
          price_label:
            cents !== null ? centsToLabel(cents) : (item.price ?? null),
          category: item.category ?? null,
          image_url: item.image ?? item.imageUrl ?? null,
        };
      });
      const { error: mErr } = await supabase.from("menu_items").insert(rows);
      if (mErr) console.error(`  ❌ ${name} menu items:`, mErr.message);
      else console.log(`  ✅ ${name} — ${rows.length} menu item(s)`);
    } else {
      console.log(`  ✅ ${name} — no menu items`);
    }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) {
    console.error("❌ NEXT_PUBLIC_SUPABASE_URL not set in .env.local");
    process.exit(1);
  }

  console.log("\n🌱 Seeding Forkeur Supabase...\n");

  await seedPlatform({
    dbPlatform: "uber_eats",
    dataFile: "uber-eats-output.json",
  });
  await seedPlatform({
    dbPlatform: "deliveroo",
    dataFile: "deliveroo-data.json",
  });
  await seedPlatform({
    dbPlatform: "takeaway",
    dataFile: "takeaway-restaurants.json",
  });

  console.log("\n🎉 Done! Check your Supabase dashboard to verify.\n");
}

main().catch((err) => {
  console.error("❌", err.message);
  process.exit(1);
});
