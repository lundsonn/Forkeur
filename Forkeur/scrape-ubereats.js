/**
 * Uber Eats local scraper — run while connected to ProtonVPN BE server.
 * Intercepts getFeedV1 API response for restaurant list, then scrapes menu.
 */

require("dotenv").config();
const puppeteer = require("puppeteer");
const fs = require("fs");

const DELIVERY_ADDRESS = "Pl. Poelaert 1, 1000 Bruxelles";
const TARGET = "mcdonald";

async function scrapeUberEats() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--lang=fr-BE"],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    );
    await page.setExtraHTTPHeaders({ "Accept-Language": "fr-BE,fr;q=0.9" });

    let feedRaw = null;
    page.on("response", async (res) => {
      if (res.url().includes("getFeedV1") && !feedRaw) {
        try {
          feedRaw = await res.text();
        } catch {}
      }
    });

    // ── Load homepage ──────────────────────────────────────────────────────────
    console.log("Loading Uber Eats...");
    await page.goto("https://www.ubereats.com/be-fr", {
      waitUntil: "networkidle2",
      timeout: 30000,
    });

    const title = await page.title();
    if (title.toLowerCase().includes("just a moment")) {
      console.error("❌ Cloudflare blocked — connect to ProtonVPN BE");
      return null;
    }
    console.log("✅ Page loaded");

    // ── Click "Find food" to reveal address input ──────────────────────────────
    await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("a, button")).find(
        (b) =>
          b.textContent.includes("Find food") ||
          b.textContent.includes("Trouver"),
      );
      if (b) b.click();
    });
    await new Promise((r) => setTimeout(r, 1200));

    // ── Type address and confirm ───────────────────────────────────────────────
    const inputSel = "#location-typeahead-home-input";
    await page.waitForSelector(inputSel, { timeout: 8000 });
    await page.click(inputSel);
    await page.type(inputSel, DELIVERY_ADDRESS, { delay: 60 });
    await new Promise((r) => setTimeout(r, 2500));
    await page.keyboard.press("ArrowDown");
    await new Promise((r) => setTimeout(r, 400));
    await page.keyboard.press("Enter");

    // ── Wait for feed API response ─────────────────────────────────────────────
    console.log("Waiting for feed...");
    const deadline = Date.now() + 15000;
    while (!feedRaw && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 500));
    }

    if (!feedRaw) {
      console.error("❌ Feed API not captured — timeout");
      return null;
    }

    // ── Parse feed ─────────────────────────────────────────────────────────────
    const feed = JSON.parse(feedRaw);
    const feedItems = feed?.data?.feedItems ?? [];
    const regularStores = feedItems.filter((i) => i.type === "REGULAR_STORE");
    console.log(`Feed: ${regularStores.length} restaurants`);

    // Map stores to clean objects
    const restaurants = regularStores.map((item) => {
      const s = item.store ?? {};
      const meta = s.meta ?? [];
      const fareMeta = meta.find((m) => m.badgeType === "FARE");
      const etaMeta = meta.find((m) => m.badgeType === "ETD");
      return {
        name: s.title?.text ?? "Unknown",
        url: s.actionUrl
          ? `https://www.ubereats.com${s.actionUrl.split("?")[0]}`
          : null,
        storeUuid: s.storeUuid ?? item.uuid,
        rating: s.rating?.text ?? "N/A",
        reviewCount:
          s.rating?.accessibilityText?.match(/(\d[\d,]+) review/)?.[1] ?? "",
        deliveryFee:
          fareMeta?.badgeData?.fare?.deliveryFee ??
          fareMeta?.text ??
          meta.find(
            (m) =>
              m.text?.toLowerCase().includes("delivery") ||
              m.text?.includes("€"),
          )?.text ??
          "Free",
        eta: etaMeta?.text ?? "N/A",
      };
    });

    // ── Find target ────────────────────────────────────────────────────────────
    const match = restaurants.find((r) =>
      r.name.toLowerCase().includes(TARGET),
    );

    if (!match) {
      console.log(
        `ℹ️  "${TARGET}" not found — first 5:`,
        restaurants.slice(0, 5).map((r) => r.name),
      );
      fs.writeFileSync(
        "ubereats-restaurants.json",
        JSON.stringify(restaurants, null, 2),
      );
      return { restaurants, target: null };
    }

    console.log(`\n✅ Found: ${match.name}`);
    console.log(
      `   Rating: ${match.rating}${match.reviewCount ? ` (${match.reviewCount})` : ""}`,
    );
    console.log(`   ETA: ${match.eta}`);
    console.log(`   Delivery: ${match.deliveryFee}`);
    console.log(`   URL: ${match.url}`);

    // ── Scrape menu ────────────────────────────────────────────────────────────
    let menuItems = [];
    if (match.url) {
      console.log("\nScraping menu...");
      await page.goto(match.url, { waitUntil: "networkidle2", timeout: 30000 });
      await new Promise((r) => setTimeout(r, 2000));

      // store-item-{uuid} li elements contain each menu item
      menuItems = await page.$$eval('li[data-testid^="store-item-"]', (els) =>
        els.slice(0, 50).map((el) => {
          const lines = (el.innerText ?? "")
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean);
          const name = lines[0] ?? "Unknown";
          const price = lines.find((l) => /^€\s*\d/.test(l)) ?? "N/A";
          const description =
            lines.find(
              (l) =>
                l !== name &&
                !l.startsWith("€") &&
                !l.includes("Buy") &&
                !l.includes("%") &&
                l.length > 8,
            ) ?? "";
          return { name, price, description };
        }),
      );

      if (menuItems.length === 0) {
        menuItems = await page.$$eval('[data-testid*="item"]', (els) =>
          els
            .filter((el) => el.innerText.includes("€"))
            .slice(0, 40)
            .map((el) => {
              const lines = (el.innerText ?? "")
                .split("\n")
                .map((l) => l.trim())
                .filter(Boolean);
              return {
                name: lines[0] ?? "Unknown",
                price: lines.find((l) => /€/.test(l)) ?? "N/A",
                description: "",
              };
            }),
        );
      }

      console.log(`Menu items: ${menuItems.length}`);
    }

    const result = {
      restaurants: restaurants.slice(0, 50),
      target: { ...match, menuItems },
    };

    fs.writeFileSync("ubereats-data.json", JSON.stringify(result, null, 2));
    console.log("\nSaved → ubereats-data.json");
    return result;
  } finally {
    await browser.close();
  }
}

module.exports = { scrapeUberEats };
if (require.main === module) scrapeUberEats().catch(console.error);
