/**
 * Deliveroo.be local scraper — run while connected to ProtonVPN BE server.
 * Navigates via address input to find restaurants near delivery address.
 */

require("dotenv").config();
const puppeteer = require("puppeteer");
const fs = require("fs");

const DELIVERY_ADDRESS = "Pl. Poelaert 1, 1000 Bruxelles";
const TARGET = "mcdonald";
const MAX_MENU_ITEMS = 30;

async function scrapeDeliveroo() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--lang=en-GB"],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    );
    await page.setExtraHTTPHeaders({ "Accept-Language": "en-GB,en;q=0.9" });

    // ── Step 1: Navigate to English homepage ─────────────────────────────────
    console.log("Opening Deliveroo.be...");
    await page.goto("https://deliveroo.be/en", {
      waitUntil: "networkidle2",
      timeout: 30000,
    });

    const title = await page.title();
    if (title.toLowerCase().includes("just a moment")) {
      console.error("❌ Cloudflare blocked — connect to ProtonVPN BE");
      return null;
    }
    console.log("✅ Page loaded:", title);

    // ── Step 2: Find and fill address input ──────────────────────────────────
    const inputSel =
      'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]';
    await page.waitForSelector(inputSel, { timeout: 10000 });
    await page.click(inputSel);
    await page.type(inputSel, DELIVERY_ADDRESS, { delay: 60 });
    await new Promise((r) => setTimeout(r, 2500));

    // ── Step 3: Click first address suggestion ───────────────────────────────
    const suggestions = await page.$$eval(
      'li[class*="suggestion"], li[class*="ccl-ee"], [role="option"], ul li',
      (els) =>
        els
          .filter(
            (el) =>
              el.textContent.includes("Bruxelles") ||
              el.textContent.includes("Brussels"),
          )
          .slice(0, 3)
          .map((el) => el.textContent.trim().slice(0, 80)),
    );
    console.log("Suggestions:", suggestions);

    // Use keyboard navigation: ArrowDown to first suggestion, Enter to confirm
    await page.keyboard.press("ArrowDown");
    await new Promise((r) => setTimeout(r, 500));
    const highlighted = await page.evaluate(() => {
      const el = document.querySelector(
        '[aria-selected="true"], li[class*="ccl-ee"]:first-child, ul li:first-child',
      );
      return el?.textContent?.trim().slice(0, 80) ?? null;
    });
    console.log("Highlighted suggestion:", highlighted);
    await page.keyboard.press("Enter");
    await new Promise((r) => setTimeout(r, 5000));
    const listingUrl = page.url();
    console.log("Listing URL:", listingUrl);

    if (!listingUrl.includes("restaurants")) {
      console.error("❌ Did not land on restaurant listing page");
      await browser.close();
      return null;
    }

    // ── Step 4: Scroll to load more, then extract cards ──────────────────────
    await page.waitForSelector('a[href*="/menu/"]', { timeout: 10000 });
    for (let i = 0; i < 10; i++) {
      await page.evaluate(() => window.scrollBy(0, 3000));
      await new Promise((r) => setTimeout(r, 600));
    }
    await new Promise((r) => setTimeout(r, 1000));

    const restaurants = await page.$$eval('a[href*="/menu/"]', (anchors) => {
      const seen = new Set();
      return anchors
        .filter((a) => {
          const slug = a.href.match(/\/menu\/([^?#]+)/)?.[1];
          if (!slug || seen.has(slug)) return false;
          seen.add(slug);
          return true;
        })
        .map((a) => {
          const slug = a.href.match(/\/menu\/([^?#]+)/)?.[1] ?? "";
          // Walk up to card container
          let card = a;
          for (let i = 0; i < 8; i++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            if (card.tagName === "LI" || card.tagName === "ARTICLE") break;
          }
          const lines = (card.innerText ?? a.innerText ?? "")
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean);

          // Card structure: [eta?, promo?, NAME, "X.X Excellent (NNN) · N.N km"]
          // Rating line: "4.6 Excellent (282) · 2.3 km"
          const ratingLineIdx = lines.findIndex((l) =>
            /^\d[.,]\d\s+(Excellent|Good|Okay|Poor)/i.test(l),
          );
          const ratingLine = ratingLineIdx >= 0 ? lines[ratingLineIdx] : null;

          // Name is the line immediately before the rating line (or last non-meta line)
          const name =
            ratingLineIdx > 0
              ? lines[ratingLineIdx - 1]
              : (lines.find(
                  (l) =>
                    !l.match(/^\d+\s*min$/) && !l.includes("€") && l.length > 3,
                ) ?? slug);

          // Rating: first number like "4.6"
          const ratingMatch = ratingLine?.match(/^(\d[.,]\d)/);
          const rating = ratingMatch ? ratingMatch[1] : "N/A";

          // Review count: (282) or (500+)
          const reviewMatch = ratingLine?.match(/\((\d[\d.,]*\+?)\)/);
          const reviewCount = reviewMatch ? reviewMatch[1] : "";

          // ETA: "30 min" or "25-45 min"
          const eta = lines.find((l) => /^\d+(-\d+)?\s*min$/i.test(l)) ?? "N/A";

          // Delivery fee: line with "delivery fee" or "livraison"
          const feeLine = lines.find(
            (l) =>
              l.toLowerCase().includes("delivery fee") ||
              l.toLowerCase().includes("livraison") ||
              /^€\d/.test(l),
          );
          const deliveryFee = feeLine ?? "N/A";

          return {
            name,
            url: a.href,
            slug,
            rating,
            reviewCount,
            eta,
            deliveryFee,
          };
        });
    });

    console.log(`Found ${restaurants.length} restaurants`);

    // ── Step 5: Find target restaurant ───────────────────────────────────────
    const match = restaurants.find(
      (r) =>
        r.name.toLowerCase().includes(TARGET) ||
        r.slug.toLowerCase().includes(TARGET),
    );

    let menuItems = [];

    if (match) {
      console.log(`\n✅ Found: ${match.name}`);
      console.log(
        `   Rating: ${match.rating} ${match.reviewCount ? `(${match.reviewCount})` : ""}`,
      );
      console.log(`   ETA: ${match.eta}`);
      console.log(`   Delivery: ${match.deliveryFee}`);
      console.log(`   URL: ${match.url}`);

      // ── Step 6: Scrape menu ─────────────────────────────────────────────────
      console.log("\nScraping menu...");
      await page.goto(match.url, { waitUntil: "networkidle2", timeout: 30000 });
      await new Promise((r) => setTimeout(r, 2000));

      menuItems = await page.$$eval(
        '[data-testid*="menu-item"], [class*="menuItem"], [class*="MenuItem"], li[class*="item"]',
        (els) =>
          els.slice(0, 30).map((el) => {
            const lines = (el.innerText ?? "")
              .split("\n")
              .map((l) => l.trim())
              .filter(Boolean);
            const price = lines.find((l) => /€\s*\d/.test(l)) ?? "N/A";
            return {
              name: lines[0] ?? "Unknown",
              price,
              description:
                lines.find(
                  (l) => l !== lines[0] && !l.includes("€") && l.length > 5,
                ) ?? "",
            };
          }),
      );
      console.log(`Menu items scraped: ${menuItems.length}`);
    } else {
      console.log(
        `ℹ️  "${TARGET}" not found — first 5:`,
        restaurants.slice(0, 5).map((r) => r.name),
      );
    }

    const result = {
      restaurants: restaurants.slice(0, 30),
      target: match ? { ...match, menuItems } : null,
      listingUrl,
    };

    fs.writeFileSync("deliveroo-data.json", JSON.stringify(result, null, 2));
    console.log("\nSaved → deliveroo-data.json");
    return result;
  } finally {
    await browser.close();
  }
}

module.exports = { scrapeDeliveroo };
if (require.main === module) scrapeDeliveroo().catch(console.error);
