#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */
// scripts/seed-supabase.js
// Match scraped platform JSON → Supabase (restaurants + platform_listings + menu_items).
// Usage: node scripts/seed-supabase.js

require("dotenv").config({ path: ".env.local" });

const fs = require("fs");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

// ── Config ────────────────────────────────────────────────────────────────────

const MIN_RESTAURANTS = 10;
const FUZZY_THRESHOLD = 3;
const DATA_DIR = path.join(__dirname, "..", "data");

// ── Supabase ──────────────────────────────────────────────────────────────────

const SUPABASE_URL =
  process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;

const SUPABASE_KEY =
  process.env.SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error("❌ Set SUPABASE_URL and SUPABASE_ANON_KEY in .env.local");
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

// ── Normalization helpers ─────────────────────────────────────────────────────

function normalizeName(s) {
  if (!s) return "";
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s*[-–—|/]\s*[a-z][\w\s]*$/, "") // drop trailing "- Ixelles", "| Brussels" etc.
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function toSlug(name) {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function uniqueSlug(base, used) {
  if (!used.has(base)) {
    used.add(base);
    return base;
  }
  let n = 2;
  while (used.has(`${base}-${n}`)) n++;
  const s = `${base}-${n}`;
  used.add(s);
  return s;
}

function parseFee(raw) {
  if (raw == null) return null;
  if (typeof raw === "number") return raw;
  const s = String(raw).trim();
  if (/^0$|free|gratuit/i.test(s)) return 0;
  const m = s.match(/(\d+)[.,](\d{2})/);
  if (m) return parseFloat(`${m[1]}.${m[2]}`);
  const m2 = s.match(/€?\s*(\d+)/);
  if (m2) return parseFloat(m2[1]);
  return null;
}

// UberEats rating is a string like "4.5 (200+)" or "4,5"
function parseRating(raw) {
  if (!raw || raw === "N/A") return { value: null, count: null };
  const s = String(raw).replace(",", ".");
  const full = s.match(/([\d.]+)\s*\(([\d.,k+]+)\)/i);
  if (full) return { value: parseFloat(full[1]), count: full[2] };
  const v = parseFloat(s);
  return { value: isNaN(v) ? null : v, count: null };
}

// review_count from scrapers may be a string like "200+" or "" — normalise to int or null
function parseReviewCount(raw) {
  if (raw == null || raw === "" || raw === "N/A") return null;
  const n = parseInt(String(raw).replace(/\D/g, ""), 10);
  return isNaN(n) ? null : n;
}

function parseEta(raw) {
  if (!raw) return { eta_min: null, eta_max: null };
  if (typeof raw === "object") {
    return { eta_min: raw.min ?? null, eta_max: raw.max ?? raw.min ?? null };
  }
  const s = String(raw);
  const range = s.match(/(\d+)\s*[-–à]\s*(\d+)/);
  if (range) return { eta_min: +range[1], eta_max: +range[2] };
  const single = s.match(/(\d+)/);
  if (single) {
    const v = +single[1];
    return { eta_min: v, eta_max: v };
  }
  return { eta_min: null, eta_max: null };
}

function levenshtein(a, b) {
  const m = a.length,
    n = b.length;
  const d = Array.from({ length: m + 1 }, (_, i) =>
    Array.from({ length: n + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)),
  );
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      d[i][j] =
        a[i - 1] === b[j - 1]
          ? d[i - 1][j - 1]
          : 1 + Math.min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1]);
  return d[m][n];
}

// ── Validation ────────────────────────────────────────────────────────────────

function loadAndValidate(filename, platform, getFee, requireFee = true) {
  const fp = path.join(DATA_DIR, filename);
  if (!fs.existsSync(fp)) throw new Error(`Missing: data/${filename}`);

  let data;
  try {
    data = JSON.parse(fs.readFileSync(fp, "utf-8"));
  } catch (e) {
    throw new Error(`Parse error in data/${filename}: ${e.message}`);
  }

  if (!Array.isArray(data) || !data.length)
    throw new Error(`data/${filename} is empty or not an array`);

  if (data.length < MIN_RESTAURANTS)
    throw new Error(
      `${platform}: ${data.length} restaurants < MIN_RESTAURANTS (${MIN_RESTAURANTS}) — scraper likely broken`,
    );

  const validFees = data.filter((r) => parseFee(getFee(r)) !== null).length;
  if (requireFee && validFees === 0)
    throw new Error(
      `${platform}: all delivery fees null/unparseable — selectors likely broke`,
    );

  return { data, validFees };
}

// ── Fuzzy lookup ──────────────────────────────────────────────────────────────

function fuzzyFind(normName, index) {
  let best = null;
  for (const [key, rec] of index) {
    const d = levenshtein(normName, key);
    if (d > 0 && d < FUZZY_THRESHOLD && (!best || d < best.d))
      best = { rec, d, key };
  }
  return best;
}

// ── Listing upsert (no unique constraint on restaurant_id+platform in DB) ─────

async function upsertListing(restaurantId, platform, row) {
  const { data: ex } = await supabase
    .from("platform_listings")
    .select("id")
    .eq("restaurant_id", restaurantId)
    .eq("platform", platform)
    .maybeSingle();

  if (ex) {
    const { data, error } = await supabase
      .from("platform_listings")
      .update(row)
      .eq("id", ex.id)
      .select("id")
      .single();
    if (error) throw error;
    return data.id;
  }

  const { data, error } = await supabase
    .from("platform_listings")
    .insert({ ...row, restaurant_id: restaurantId, platform })
    .select("id")
    .single();
  if (error) throw error;
  return data.id;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  // Validate all three files before writing anything
  console.log(
    "\n── Validation ──────────────────────────────────────────────────────────────\n",
  );

  let uberRaw, deliverooRaw, takeawayRaw;
  let uberFees, deliverooFees, takeawayFees;
  try {
    // Actual scraper output fields:
    //   ubereats:  { name, url, delivery_fee (float), eta (string), rating (string), lat, lng }
    //   deliveroo: { name, url, slug, rating (string), review_count, eta }  — no delivery_fee
    //   takeaway:  { name, url, slug, rating (string), review_count, eta, delivery_fee (string) }
    ({ data: uberRaw, validFees: uberFees } = loadAndValidate(
      "ubereats.json",
      "ubereats",
      (r) => r.delivery_fee,
    ));
    ({ data: deliverooRaw, validFees: deliverooFees } = loadAndValidate(
      "deliveroo.json",
      "deliveroo",
      (r) => r.delivery_fee,
      false, // deliveroo scraper doesn't extract delivery fee
    ));
    ({ data: takeawayRaw, validFees: takeawayFees } = loadAndValidate(
      "takeaway.json",
      "takeaway",
      (r) => r.delivery_fee,
    ));
  } catch (e) {
    console.error("❌ Validation gate failed:", e.message);
    process.exit(1);
  }

  const pct = (v, total) => `${Math.round((100 * v) / total)}%`;
  console.log(
    `  ubereats:  ${uberRaw.length} restaurants, ${pct(uberFees, uberRaw.length)} valid fees`,
  );
  console.log(
    `  deliveroo: ${deliverooRaw.length} restaurants, ${pct(deliverooFees, deliverooRaw.length)} valid fees`,
  );
  console.log(
    `  takeaway:  ${takeawayRaw.length} restaurants, ${pct(takeawayFees, takeawayRaw.length)} valid fees`,
  );
  console.log("\n✅ All gates passed.\n");

  // ── Build in-memory restaurant map ───────────────────────────────────────────

  console.log(
    "── Matching ─────────────────────────────────────────────────────────────────\n",
  );

  const recs = []; // final restaurant records
  const usedSlugs = new Set();
  const index = new Map(); // normName -> rec (non-chain entries only, for lookup)
  const chains = new Set(); // normNames known to be multi-location chains
  const warnings = [];

  function mkRec(name, opts = {}) {
    const base = opts.slugBase || toSlug(name);
    const rec = {
      name,
      slug: uniqueSlug(base, usedSlugs),
      cuisine: opts.cuisine ?? null,
      neighborhood: opts.neighborhood ?? null,
      lat: opts.lat ?? null,
      lng: opts.lng ?? null,
      needs_review: opts.needs_review ?? false,
      _uber: null,
      _deliveroo: null,
      _takeaway: null,
    };
    recs.push(rec);
    return rec;
  }

  // UberEats as spine — provides coords; cuisine inferred server-side by db.py
  const uberByNorm = new Map();
  for (const r of uberRaw) {
    const k = normalizeName(r.name);
    if (!uberByNorm.has(k)) uberByNorm.set(k, []);
    uberByNorm.get(k).push(r);
  }

  for (const [normName, entries] of uberByNorm) {
    if (entries.length > 1) {
      chains.add(normName);
      warnings.push(
        `CHAIN ubereats "${normName}" — ${entries.length} locations, all needs_review`,
      );
    }
    for (let i = 0; i < entries.length; i++) {
      const r = entries[i];
      const isChain = entries.length > 1;
      const rec = mkRec(r.name, {
        slugBase: isChain ? `${toSlug(r.name)}-${i + 1}` : undefined,
        cuisine: null, // not in scraper output; db.py infers it from name
        neighborhood: null,
        lat: r.lat ?? null,
        lng: r.lng ?? null,
        needs_review: isChain,
      });
      rec._uber = r;
      if (!isChain) index.set(normName, rec);
    }
  }

  // Match a secondary platform (Deliveroo / Takeaway) into the existing map
  function matchSecondary(rawData, field, getName) {
    const byNorm = new Map();
    for (const r of rawData) {
      const k = normalizeName(getName(r));
      if (!byNorm.has(k)) byNorm.set(k, []);
      byNorm.get(k).push(r);
    }

    for (const [normName, entries] of byNorm) {
      const isChain = entries.length > 1;
      if (isChain) {
        chains.add(normName);
        warnings.push(
          `CHAIN ${field.slice(1)} "${normName}" — ${entries.length} locations, all needs_review`,
        );
      }

      for (let i = 0; i < entries.length; i++) {
        const r = entries[i];
        const name = getName(r);

        // Chain on this platform — always a separate row
        if (isChain) {
          const rec = mkRec(name, {
            slugBase: `${toSlug(name)}-${i + 1}`,
            needs_review: true,
          });
          rec[field] = r;
          continue;
        }

        // Name matches a known chain from another platform — ambiguous, don't auto-merge
        if (chains.has(normName)) {
          const rec = mkRec(name, { needs_review: true });
          rec[field] = r;
          warnings.push(
            `AMBIGUOUS ${field.slice(1)} "${name}" — matches known chain, new row, needs_review`,
          );
          continue;
        }

        // Exact match
        const exact = index.get(normName);
        if (exact) {
          exact[field] = r;
          continue;
        }

        // Fuzzy match (close but not identical)
        const fuzzy = fuzzyFind(normName, index);
        if (fuzzy) {
          fuzzy.rec[field] = r;
          fuzzy.rec.needs_review = true;
          warnings.push(
            `FUZZY ${field.slice(1)} "${name}" → "${fuzzy.rec.name}" (distance ${fuzzy.d})`,
          );
          continue;
        }

        // No match — new restaurant (first seen on this platform)
        const rec = mkRec(name);
        rec[field] = r;
        index.set(normName, rec);
      }
    }
  }

  matchSecondary(deliverooRaw, "_deliveroo", (r) => r.name);
  matchSecondary(takeawayRaw, "_takeaway", (r) => r.name);

  if (warnings.length) {
    for (const w of warnings) console.warn("  ⚠", w);
    console.log();
  }

  // ── Write to Supabase ─────────────────────────────────────────────────────

  console.log(
    `── Upserting ${recs.length} restaurants ─────────────────────────────────────────\n`,
  );

  let ok = 0,
    errs = 0,
    multi = 0,
    flagged = 0;
  const scrapedAt = new Date().toISOString();

  for (const rec of recs) {
    const { data: restaurant, error: rErr } = await supabase
      .from("restaurants")
      .upsert(
        {
          name: rec.name,
          slug: rec.slug,
          cuisine: rec.cuisine,
          neighborhood: rec.neighborhood,
          lat: rec.lat,
          lng: rec.lng,
          needs_review: rec.needs_review,
        },
        { onConflict: "slug" },
      )
      .select("id")
      .single();

    if (rErr) {
      console.error(`  ❌ ${rec.name}:`, rErr.message);
      errs++;
      continue;
    }

    const platforms = [];

    if (rec._uber) {
      const r = rec._uber;
      // Scraper output: { name, url, delivery_fee (float), eta (string), rating (string), lat, lng }
      const { eta_min, eta_max } = parseEta(r.eta);
      const fee = r.delivery_fee != null ? r.delivery_fee : null; // already a float
      const { value: ratingVal, count: ratingCount } = parseRating(r.rating);
      try {
        const lid = await upsertListing(restaurant.id, "uber_eats", {
          url: r.url ?? null,
          rating: ratingVal != null ? parseFloat(ratingVal.toFixed(2)) : null,
          review_count: parseReviewCount(ratingCount),
          eta_min,
          eta_max,
          delivery_fee: fee,
          min_order: null,
          is_available: !(eta_min == null && fee == null),
          scraped_at: scrapedAt,
        });
        platforms.push("uber_eats");

        // menu is only present if run with --menus; scrapers write it directly to DB otherwise
        if (r.menu?.length) {
          await supabase.from("menu_items").delete().eq("listing_id", lid);
          const items = [];
          for (const cat of r.menu) {
            for (const item of cat.catalogItems ?? []) {
              items.push({
                listing_id: lid,
                catalog_name: cat.catalogName ?? null,
                title: item.title,
                price: item.price != null ? parseFee(item.price) : null,
              });
            }
          }
          if (items.length) {
            const { error: mErr } = await supabase
              .from("menu_items")
              .insert(items);
            if (mErr) console.error(`  ❌ menu ${rec.name}:`, mErr.message);
          }
        }
      } catch (e) {
        console.error(`  ❌ [uber_eats] ${rec.name}:`, e.message);
      }
    }

    if (rec._deliveroo) {
      const r = rec._deliveroo;
      // Scraper output: { name, url, slug, rating (string), review_count, eta }  — no delivery_fee
      const { eta_min, eta_max } = parseEta(r.eta);
      const { value: ratingVal } = parseRating(r.rating);
      try {
        await upsertListing(restaurant.id, "deliveroo", {
          url: r.url ?? null,
          rating: ratingVal != null ? parseFloat(ratingVal.toFixed(2)) : null,
          review_count: parseReviewCount(r.review_count),
          eta_min,
          eta_max,
          delivery_fee: null, // not extracted by deliveroo scraper
          min_order: null,
          is_available: eta_min != null,
          scraped_at: scrapedAt,
        });
        platforms.push("deliveroo");
      } catch (e) {
        console.error(`  ❌ [deliveroo] ${rec.name}:`, e.message);
      }
    }

    if (rec._takeaway) {
      const r = rec._takeaway;
      // Scraper output: { name, url, slug, rating (string), review_count, eta, delivery_fee (string) }
      const { eta_min, eta_max } = parseEta(r.eta);
      const fee = parseFee(r.delivery_fee);
      const { value: ratingVal } = parseRating(r.rating);
      try {
        await upsertListing(restaurant.id, "takeaway", {
          url: r.url ?? null,
          rating: ratingVal != null ? parseFloat(ratingVal.toFixed(2)) : null,
          review_count: parseReviewCount(r.review_count),
          eta_min,
          eta_max,
          delivery_fee: fee,
          min_order: null, // not extracted by takeaway scraper
          is_available: !(eta_min == null && fee == null),
          scraped_at: scrapedAt,
        });
        platforms.push("takeaway");
      } catch (e) {
        console.error(`  ❌ [takeaway] ${rec.name}:`, e.message);
      }
    }

    if (rec.needs_review) flagged++;
    if (platforms.length >= 2) multi++;

    const flag = rec.needs_review ? "  ⚠ needs_review" : "";
    console.log(
      `  ✅ ${rec.name}  [${platforms.join(" + ") || "no listings"}]${flag}`,
    );
    ok++;
  }

  console.log(
    "\n── Summary ──────────────────────────────────────────────────────────────────\n",
  );
  console.log(`  Total restaurants  : ${recs.length}`);
  console.log(`  Written OK         : ${ok}`);
  console.log(`  Errors             : ${errs}`);
  console.log(`  Matched 2+ platforms: ${multi}`);
  console.log(
    `  needs_review queue : ${flagged}  ← resolve in Supabase dashboard`,
  );
  if (warnings.length) {
    console.log(`\n  ⚠ ${warnings.length} warning(s):`);
    for (const w of warnings) console.log(`     ${w}`);
  }
  console.log();
}

main().catch((e) => {
  console.error("❌ Fatal:", e.message);
  process.exit(1);
});
