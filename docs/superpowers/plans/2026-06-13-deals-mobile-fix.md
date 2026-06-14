# Deals page — mobile UX fixes

**Status:** Handoff — not started  
**Prereq:** Deals UX Rework (Tasks 1–6) ✅ complete  
**File to edit:** `forkeur-app/components/DealsClient.tsx` (primary), `forkeur-app/components/FeaturedStrip.tsx` (minor)  
**Dev server:** `cd forkeur-app && npm run dev -- --port 30000` (port 30000, NOT 3000)  
**Backend:** SSH tunnel to prod — `ssh -i ~/.ssh/id_ed25519_forkeur -N -L 8000:localhost:8000 root@178.104.57.72`  
**Screenshots:** `docs/superpowers/deals-mobile-top.png`, `docs/superpowers/deals-mobile-cards.png`

---

## What's broken on mobile (390px / iPhone 14)

### Bug 1 — CRITICAL: Badge text overflows card width

**Where:** Every `DealCard` in the grid.  
**What:** The promo label badge (`<div className={...badgeColor...} rounded-lg px-3 py-2 flex-shrink-0">`) sits in a flex row with `flex-shrink-0`. On mobile the label text (scraped raw strings like *"Chicken Ky-Halal 4,7 (230+) Gratuit Commande gr…"*, *"Achetez 2, le moins cher à moitié prix s…"*) bleeds past the card edge.  
**Root cause:** Badge has `flex-shrink-0` so it won't compress, and no `max-w` or `overflow-hidden` on the text.

**Fix:** Switch the card layout from a badge-beside-meta row to **badge full-width on top** — closer to the FeaturedCard pattern in `FeaturedStrip.tsx`. Specifically:

```tsx
// BEFORE (flex row, badge left, meta right)
<div className="flex items-start gap-3 p-4">
  <div className={`${badgeColor} rounded-lg px-3 py-2 flex-shrink-0`}>
    <span className="text-lg font-bold leading-tight">{deal.label}</span>
  </div>
  <div className="ml-auto text-right text-xs text-stone-500 space-y-0.5">
    {/* platform dot + rating */}
  </div>
</div>

// AFTER (badge full width, meta row below)
<div className={`${badgeColor} px-4 py-4 relative`}>
  <p className="text-base font-bold leading-snug line-clamp-2">{deal.label}</p>
  <div className="absolute top-2 right-3 text-right text-xs opacity-80 space-y-0.5">
    <div className="flex items-center justify-end gap-1">
      <span className={`inline-block w-2 h-2 rounded-full ${dotColor} opacity-90`} />
      <span>{t(`platform.${deal.platform}`)}</span>
    </div>
    {deal.rating && (
      <div>★ {deal.rating.toFixed(1)}{deal.review_count ? ` (${deal.review_count})` : ''}</div>
    )}
  </div>
</div>
<div className="px-4 py-3 flex flex-col gap-1.5 flex-1">
  {/* rest unchanged */}
</div>
```

This matches the `FeaturedCard` pattern (badge color fills top zone, text inside) and eliminates overflow. `line-clamp-2` caps very long labels at 2 lines.

---

### Bug 2 — Platform filter row wraps to 3 lines; sort floats badly

**Where:** Sticky filter bar, row 2 (`flex items-center gap-2 mt-2 flex-wrap`).  
**What:** On 390px, "UberEats" fits on line 1 next to "All", "Deliveroo" and "Sort: Best deal" share line 2, "Takeaway" falls to line 3. Result: sticky bar is ~160px tall and hides ~20% of viewport while scrolling.

**Fix:** Make the platform row horizontally scrollable (same pattern as type filter row 1), and move the sort select to its own row below:

```tsx
{/* Row 2: platform filters — horizontal scroll, no wrap */}
<div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none mt-2">
  {PLATFORM_FILTERS.map(({ key, labelKey, dotColor }) => (
    <button key={key} onClick={() => setActivePlatform(key)}
      className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
        activePlatform === key ? 'bg-stone-800 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
      }`}>
      {dotColor && <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />}
      {t(labelKey)}
    </button>
  ))}
</div>

{/* Row 3: sort — full width, right-aligned */}
<div className="flex items-center justify-end gap-1.5 mt-2">
  <span className="text-xs text-stone-400">{t('deals.sort_label')}:</span>
  <select value={sortMode} onChange={e => setSortMode(e.target.value as SortMode)}
    className="text-sm text-stone-700 bg-transparent border-0 outline-none cursor-pointer pr-1">
    {SORT_OPTIONS.map(({ value, i18nKey }) => (
      <option key={value} value={value}>{t(i18nKey)}</option>
    ))}
  </select>
</div>
```

On desktop (sm+), consolidate back to 2 rows: use `sm:flex-row sm:flex-nowrap sm:overflow-visible` on row 2, and `sm:hidden` on the separate sort row while showing the original inline sort. Or simplest: just keep 3 rows — the sticky bar is still only ~100px at most on mobile, acceptable.

---

### Issue 3 — FeaturedStrip second card clips text at right edge

**Where:** `FeaturedStrip.tsx` — `FeaturedCard` width is `w-64 sm:w-72`.  
**What:** At 390px, `w-64` = 256px. Two cards + gap = ~524px, so the second card is partially visible (correct — horizontal scroll affordance). But the card text *inside* the visible portion is okay — just the badge text "Livraiso..." is cut, which is intentional for the peek affordance.  
**Verdict:** No fix needed. This is correct scroll-peek UX. The `line-clamp-2` fix from Bug 1 could optionally be mirrored here for very long labels.

---

## Verification checklist

After fixing:

1. Emulate iPhone 14 (390×844) in browser devtools
2. Filter bar: max 2 rows on mobile (type row + platform row); sort on its own slim row
3. All deal cards: badge text fully visible, no horizontal overflow
4. FeaturedStrip: horizontal scroll works, peek of second card visible
5. Sticky filter bar: collapses correctly while scrolling, doesn't eat too much viewport
6. Run `cd forkeur-app && npx tsc --noEmit` — must be clean
7. Run `cd forkeur-app && npx vitest run` — 208/208 pass (no logic change expected)
8. Desktop at 1280px: grid still 3 columns, filter bar still 2 rows, no regression

---

## Constraints (carry forward always)

- Never `git commit` without explicit ask
- Port 30000 (never 3000)
- Stone/white/orange theme only
- `import type { Platform } from './basket'` (NOT `'./queries'`)
- All new UI strings in EN + FR + NL simultaneously
