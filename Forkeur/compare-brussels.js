/**
 * forkeur — Brussels price comparison
 * Uber Eats · Deliveroo.be · Takeaway.be
 *
 * All scrapers run locally via Puppeteer + ProtonVPN BE.
 * Run: node compare-brussels.js
 */

const fs = require("fs");
const { execSync } = require("child_process");
const { scrapeUberEats } = require("./scrape-ubereats");
const { scrapeDeliveroo } = require("./scrape-deliveroo");
const { scrapeTakeaway } = require("./scrape-takeaway");

const RESTAURANT_NAME = "McDonald's";

async function main() {
  console.log("\n🔍 forkeur — Brussels price comparison");
  console.log(`   Restaurant: "${RESTAURANT_NAME}"`);
  console.log("   Platforms:  Uber Eats · Deliveroo.be · Takeaway.be");
  console.log("   Running all 3 scrapers in parallel...\n");

  const [uberResult, deliverooResult, takeawayResult] =
    await Promise.allSettled([
      scrapeUberEats(),
      scrapeDeliveroo(),
      scrapeTakeaway(),
    ]);

  const results = {};

  const normalize = (platform, result) => {
    if (!result?.target) return null;
    const t = result.target;
    return {
      name: t.name ?? "Unknown",
      deliveryFee: t.deliveryFee ?? "N/A",
      eta: t.eta ?? "N/A",
      rating: t.rating ?? "N/A",
      reviewCount: t.reviewCount ?? "",
      url: t.url ?? null,
      menuItems: (t.menuItems ?? []).slice(0, 30),
    };
  };

  if (uberResult.status === "fulfilled" && uberResult.value?.target) {
    results.uberEats = normalize("uberEats", uberResult.value);
    console.log(
      `✅ Uber Eats: ${results.uberEats.name} (${results.uberEats.menuItems.length} menu items)`,
    );
  } else {
    console.warn(
      "⚠️  Uber Eats failed:",
      uberResult.reason?.message ?? "no target found",
    );
  }

  if (deliverooResult.status === "fulfilled" && deliverooResult.value?.target) {
    results.deliveroo = normalize("deliveroo", deliverooResult.value);
    console.log(
      `✅ Deliveroo: ${results.deliveroo.name} (${results.deliveroo.menuItems.length} menu items)`,
    );
  } else {
    console.warn(
      "⚠️  Deliveroo failed:",
      deliverooResult.reason?.message ?? "no target found",
    );
  }

  if (takeawayResult.status === "fulfilled" && takeawayResult.value?.target) {
    results.takeaway = normalize("takeaway", takeawayResult.value);
    console.log(
      `✅ Takeaway: ${results.takeaway.name} (${results.takeaway.menuItems.length} menu items)`,
    );
  } else {
    console.warn(
      "⚠️  Takeaway failed:",
      takeawayResult.reason?.message ?? "no target found",
    );
  }

  fs.writeFileSync(
    "compare-brussels-output.json",
    JSON.stringify(results, null, 2),
  );

  const html = generateHTML(results);
  fs.writeFileSync("comparison-brussels.html", html);
  console.log("\n✅ Report saved → comparison-brussels.html");

  try {
    execSync('open "comparison-brussels.html"');
    console.log("🌐 Opened in browser\n");
  } catch {
    console.log("Open manually: open comparison-brussels.html\n");
  }
}

// ── HTML Generator ─────────────────────────────────────────────────────────────

const PLATFORMS = [
  {
    key: "uberEats",
    label: "Uber Eats",
    emoji: "🍔",
    color: "#06C167",
    bg: "#f0fdf4",
    border: "#86efac",
  },
  {
    key: "deliveroo",
    label: "Deliveroo",
    emoji: "🛵",
    color: "#00CCBC",
    bg: "#f0fdfa",
    border: "#5eead4",
  },
  {
    key: "takeaway",
    label: "Takeaway.be",
    emoji: "🟠",
    color: "#FF8000",
    bg: "#fff7ed",
    border: "#fdba74",
  },
];

function generateHTML(results) {
  const withData = PLATFORMS.filter((p) => results[p.key]);
  const withoutData = PLATFORMS.filter((p) => !results[p.key]);

  const platformCards = withData
    .map(({ key, label, emoji, color, bg, border }) => {
      const r = results[key];
      const menuRows = r.menuItems
        .map(
          (item) => `
      <tr>
        <td class="item-name">${escHtml(item.name)}${item.description ? `<div class="item-desc">${escHtml(item.description.slice(0, 90))}${item.description.length > 90 ? "…" : ""}</div>` : ""}</td>
        <td class="item-price">${escHtml(String(item.price))}</td>
      </tr>`,
        )
        .join("");

      return `
    <div class="platform-card" style="border-color:${border};background:${bg}">
      <div class="platform-header" style="background:${color}">
        <span class="platform-emoji">${emoji}</span>
        <span class="platform-name">${label}</span>
        ${r.url ? `<a href="${escHtml(r.url)}" target="_blank" class="platform-link">Open ↗</a>` : ""}
      </div>
      <div class="restaurant-info">
        <div class="restaurant-name">${escHtml(r.name)}</div>
        <div class="meta-row">
          <span class="badge fee">${escHtml(String(r.deliveryFee))}</span>
          <span class="badge eta">⏱ ${escHtml(String(r.eta))}</span>
          ${r.rating !== "N/A" ? `<span class="badge rating">⭐ ${escHtml(String(r.rating))}${r.reviewCount ? ` (${r.reviewCount})` : ""}</span>` : ""}
        </div>
      </div>
      ${
        r.menuItems.length > 0
          ? `
      <div class="menu-section">
        <div class="menu-title">Menu items (${r.menuItems.length})</div>
        <table class="menu-table">
          <thead><tr><th>Item</th><th>Price</th></tr></thead>
          <tbody>${menuRows}</tbody>
        </table>
      </div>`
          : ""
      }
    </div>`;
    })
    .join("\n");

  const noDataCards = withoutData
    .map(
      ({ label, emoji, color }) => `
    <div class="no-data-card" style="border-color:#e2e8f0">
      <div class="platform-header" style="background:${color};opacity:0.6">
        <span class="platform-emoji">${emoji}</span>
        <span class="platform-name">${label}</span>
      </div>
      <div class="no-data-body">⚠️ No data — check ProtonVPN connection</div>
    </div>`,
    )
    .join("\n");

  const cols =
    withData.length === 3
      ? "repeat(3,1fr)"
      : withData.length === 2
        ? "repeat(2,1fr)"
        : "1fr";

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>forkeur — ${RESTAURANT_NAME} Brussels</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #1e293b; }
  header { background: #0f172a; color: white; padding: 24px 32px; }
  header h1 { font-size: 1.5rem; }
  header p  { color: #64748b; font-size: 0.875rem; margin-top: 4px; }
  .container { max-width: 1400px; margin: 0 auto; padding: 32px 24px; }
  .grid { display: grid; grid-template-columns: ${cols}; gap: 20px; margin-bottom: 24px; }
  .platform-card { border: 2px solid; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .no-data-card  { border: 2px dashed; border-radius: 12px; overflow: hidden; opacity: 0.7; }
  .platform-header { display: flex; align-items: center; gap: 10px; padding: 14px 18px; color: white; }
  .platform-emoji  { font-size: 1.4rem; }
  .platform-name   { font-size: 1.1rem; font-weight: 700; flex: 1; }
  .platform-link   { color: rgba(255,255,255,0.9); font-size: 0.8rem; text-decoration: none; border: 1px solid rgba(255,255,255,0.4); border-radius: 6px; padding: 2px 8px; }
  .platform-link:hover { background: rgba(255,255,255,0.15); }
  .no-data-body    { padding: 32px; text-align: center; color: #94a3b8; font-size: 0.9rem; }
  .restaurant-info { padding: 16px 18px 0; }
  .restaurant-name { font-size: 1rem; font-weight: 600; margin-bottom: 10px; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 8px; }
  .badge { font-size: 0.8rem; padding: 4px 10px; border-radius: 20px; background: white; border: 1px solid #e2e8f0; }
  .badge.rating { background: #fefce8; border-color: #fde047; }
  .badge.fee    { background: #f0f9ff; border-color: #7dd3fc; }
  .badge.eta    { background: #fdf4ff; border-color: #e879f9; }
  .menu-section { padding: 16px 18px 18px; }
  .menu-title   { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #94a3b8; margin-bottom: 10px; }
  .menu-table   { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .menu-table th { text-align: left; padding: 6px 8px; color: #64748b; font-weight: 500; border-bottom: 1px solid #e2e8f0; }
  .menu-table td { padding: 8px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
  .menu-table tr:last-child td { border-bottom: none; }
  .item-name  { font-weight: 500; }
  .item-desc  { font-size: 0.75rem; color: #94a3b8; margin-top: 2px; font-weight: 400; }
  .item-price { white-space: nowrap; font-weight: 700; text-align: right; color: #0f172a; }
  footer { text-align: center; padding: 24px; color: #94a3b8; font-size: 0.8rem; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>🍟 forkeur — ${escHtml(RESTAURANT_NAME)} · Brussels</h1>
  <p>Uber Eats · Deliveroo.be · Takeaway.be · ${new Date().toLocaleString("en-GB", { dateStyle: "long", timeStyle: "short" })}</p>
</header>
<div class="container">
  <div class="grid">
    ${platformCards}
    ${noDataCards}
  </div>
</div>
<footer>forkeur · Local scrapers · Prices may vary · Requires ProtonVPN BE</footer>
</body>
</html>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

main().catch((err) => {
  console.error("❌ Error:", err.message);
  process.exit(1);
});
