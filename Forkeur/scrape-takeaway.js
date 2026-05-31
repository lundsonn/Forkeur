/**
 * Takeaway.be local scraper — run while connected to ProtonVPN BE server.
 * Parses SSR + lazy-loaded restaurant list, extracts McDonald's data.
 */

require("dotenv").config();
const puppeteer = require("puppeteer");
const fs = require("fs");

const LISTING_URL =
  "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000";
const TARGET = "mcdonald";

async function scrapeTakeaway() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox"],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    );

    await page.goto(LISTING_URL, { waitUntil: "networkidle2", timeout: 30000 });

    const title = await page.title();
    if (
      title.toLowerCase().includes("just a moment") ||
      title.toLowerCase().includes("cloudflare")
    ) {
      console.error("❌ Cloudflare blocked — connect to ProtonVPN BE");
      return null;
    }

    console.log("✅ Page loaded:", title);

    // Scroll to load lazy content
    console.log("Scrolling to load restaurants...");
    for (let i = 0; i < 8; i++) {
      await page.evaluate(() => window.scrollBy(0, 3000));
      await new Promise((r) => setTimeout(r, 800));
    }
    await new Promise((r) => setTimeout(r, 1000));

    // Extract all restaurant cards
    const restaurants = await page.$$eval(
      '[data-qa="restaurant-card"]',
      (cards) => {
        return cards.map((card) => {
          const link = card.querySelector('a[href*="/menu/"]');
          const url = link?.href ?? "";
          const slug = url.match(/\/menu\/([^?#]+)/)?.[1] ?? "";

          // Name: h2/h3 or heading element, or link text
          const nameEl = card.querySelector(
            "h2, h3, [data-qa*='name'], [class*='name']",
          );
          const name =
            nameEl?.textContent?.trim() || link?.textContent?.trim() || slug;

          // All text content split into lines
          const lines = (card.innerText ?? "")
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean);

          // Rating: e.g. "4,7"
          const rating = lines.find((l) => /^\d[,\.]\d$/.test(l)) ?? "N/A";

          // Reviews: e.g. "(270+)" or "(3.700+)"
          const reviewCount =
            lines
              .find((l) => /^\(\d[\d.,]*\+?\)$/.test(l))
              ?.replace(/[()]/g, "") ?? "";

          // ETA: "25-45 min"
          const eta = lines.find((l) => /\d+-\d+\s*min/.test(l)) ?? "N/A";

          // Delivery fee
          const feeLine = lines.find((l) =>
            l.toLowerCase().includes("livraison"),
          );
          const deliveryFee = feeLine ?? "N/A";

          // Min order
          const minOrder =
            lines.find((l) => l.toLowerCase().includes("min.")) ?? "";

          return {
            name,
            url,
            slug,
            rating,
            reviewCount,
            eta,
            deliveryFee,
            minOrder,
          };
        });
      },
    );

    // Deduplicate by slug
    const seen = new Set();
    const unique = restaurants.filter((r) => {
      if (!r.slug || seen.has(r.slug)) return false;
      seen.add(r.slug);
      return true;
    });

    console.log(`Found ${unique.length} unique restaurants`);

    const matches = unique.filter(
      (r) =>
        r.name.toLowerCase().includes(TARGET) ||
        r.slug.toLowerCase().includes(TARGET),
    );

    if (matches.length > 0) {
      console.log(`\n✅ Found ${matches.length} McDonald's location(s):`);
      for (const m of matches) {
        console.log(`  ${m.name}`);
        console.log(
          `    Rating: ${m.rating} ${m.reviewCount ? `(${m.reviewCount})` : ""}`,
        );
        console.log(`    ETA: ${m.eta}`);
        console.log(`    Delivery: ${m.deliveryFee}`);
        console.log(`    Min order: ${m.minOrder}`);
        console.log(`    URL: ${m.url}`);
      }
    } else {
      console.log(`ℹ️  "${TARGET}" not found in ${unique.length} restaurants`);
      console.log(
        "First 5:",
        unique.slice(0, 5).map((r) => r.name),
      );
    }

    fs.writeFileSync(
      "takeaway-restaurants.json",
      JSON.stringify(unique, null, 2),
    );
    console.log(
      `\nSaved ${unique.length} restaurants → takeaway-restaurants.json`,
    );
    return { restaurants: unique, target: matches[0] ?? null };
  } finally {
    await browser.close();
  }
}

module.exports = { scrapeTakeaway };
if (require.main === module) scrapeTakeaway().catch(console.error);
