/**
 * Seed Brussels data into Supabase
 * Reads the Apify output files and upserts into your database.
 *
 * Prerequisites:
 *   1. Run the scrapers first: npm run compare:brussels
 *   2. Add SUPABASE_URL + SUPABASE_SERVICE_KEY to your .env file
 *
 * Run: node supabase/seed-brussels.js
 */

require("dotenv").config({ path: "../.env" });
const fs = require("fs");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Extract a clean euro cent value from messy platform strings.
 *  "Les frais de livraison s'élèvent à 3.99 €." → 399
 *  "€2.49" → 249
 *  "Free" / "0" → 0
 */
function parseFeeCents(raw) {
  if (!raw) return null;
  const str = String(raw);
  if (/free|gratuit/i.test(str)) return 0;
  const match = str.match(/(\d+)[.,](\d{2})/);
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2]);
  const whole = str.match(/(\d+)/);
  if (whole) return parseInt(whole[1]) * 100;
  return null;
}

/** Format cents as a label: 399 → "€3.99", 0 → "Free" */
function centsToLabel(cents) {
  if (cents === null || cents === undefined) return null;
  if (cents === 0) return "Free";
  return `€${(cents / 100).toFixed(2)}`;
}

/** Parse ETA strings into min/max minutes.
 *  "Commande livrée dans 10 à 10 min" → { min: 10, max: 10, label: "10 min" }
 *  "20-30 min" → { min: 20, max: 30, label: "20–30 min" }
 */
function parseEta(raw) {
  if (!raw) return { min: null, max: null, label: null };
  const range = raw.match(/(\d+)\s*(?:à|to|-|–)\s*(\d+)/);
  if (range) {
    const min = parseInt(range[1]);
    const max = parseInt(range[2]);
    return { min, max, label: min === max ? `${min} min` : `${min}–${max} min` };
  }
  const single = raw.match(/(\d+)\s*min/i);
  if (single) {
    const v = parseInt(single[1]);
    return { min: v, max: v, label: `${v} min` };
  }
  return { min: null, max: null, label: raw };
}

/** Parse "€8.00" or "8.00" into cents: 800 */
function priceToCents(raw) {
  if (!raw || raw === "N/A") return null;
  const match = String(raw).match(/(\d+)[.,](\d{2})/);
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2]);
  return null;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_KEY; // use service key for seeding

  if (!supabaseUrl || !supabaseKey) {
    console.error("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env");
    console.error("   Get these from: Supabase Dashboard → Settings → API");
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  // Load the Apify output file
  const outputPath = path.join(__dirname, "../compare-brussels-output.json");
  if (!fs.existsSync(outputPath)) {
    console.error("❌ compare-brussels-output.json not found.");
    console.error("   Run npm run compare:brussels first.");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(outputPath, "utf-8"));
  console.log("\n🌱 Seeding Brussels data into Supabase...\n");

  // ── Process each platform ──────────────────────────────────────────────────
  const platformMap = {
    uberEats:  "uber_eats",
    deliveroo: "deliveroo",
    justEat:   "takeaway",
  };

  for (const [jsKey, dbPlatform] of Object.entries(platformMap)) {
    const platformData = data[jsKey];
    if (!platformData) {
      console.log(`⏭  No ${jsKey} data — skipping`);
      continue;
    }

    console.log(`📥 Processing ${jsKey}: "${platformData.name}"`);

    // 1. Upsert restaurant (match by name + city)
    const { data: restaurant, error: rErr } = await supabase
      .from("restaurants")
      .upsert(
        { name: platformData.name, city: "Brussels" },
        { onConflict: "name,city", ignoreDuplicates: false }
      )
      .select()
      .single();

    if (rErr) { console.error("   ❌ Restaurant error:", rErr.message); continue; }
    console.log(`   ✅ Restaurant: ${restaurant.id}`);

    // 2. Parse delivery info
    const feeCents = parseFeeCents(platformData.deliveryFee);
    const eta = parseEta(platformData.eta);

    // 3. Upsert platform listing
    const { data: listing, error: lErr } = await supabase
      .from("platform_listings")
      .upsert(
        {
          restaurant_id:      restaurant.id,
          platform:           dbPlatform,
          platform_url:       platformData.url ?? null,
          delivery_fee_cents: feeCents,
          delivery_fee_label: centsToLabel(feeCents),
          eta_min:            eta.min,
          eta_max:            eta.max,
          eta_label:          eta.label,
          rating:             platformData.rating !== "N/A" ? parseFloat(platformData.rating) : null,
          rating_count:       platformData.reviewCount || null,
          hero_image_url:     platformData.heroImage ?? null,
          scraped_at:         new Date().toISOString(),
        },
        { onConflict: "restaurant_id,platform" }
      )
      .select()
      .single();

    if (lErr) { console.error("   ❌ Listing error:", lErr.message); continue; }
    console.log(`   ✅ Listing: ${listing.id} (fee: ${centsToLabel(feeCents)}, eta: ${eta.label})`);

    // 4. Delete old menu items for this listing, then insert fresh ones
    await supabase.from("menu_items").delete().eq("listing_id", listing.id);

    const menuRows = (platformData.menuItems ?? []).map((item) => {
      const cents = priceToCents(item.price);
      return {
        listing_id:   listing.id,
        name:         item.name ?? "Unknown",
        description:  item.description || null,
        price_cents:  cents,
        price_label:  cents !== null ? centsToLabel(cents) : (item.price ?? null),
        image_url:    item.image ?? null,
      };
    });

    if (menuRows.length > 0) {
      const { error: mErr } = await supabase.from("menu_items").insert(menuRows);
      if (mErr) console.error("   ❌ Menu items error:", mErr.message);
      else console.log(`   ✅ ${menuRows.length} menu items inserted`);
    }
  }

  console.log("\n🎉 Done! Check your Supabase dashboard to verify the data.\n");
}

main().catch((err) => {
  console.error("❌", err.message);
  process.exit(1);
});
