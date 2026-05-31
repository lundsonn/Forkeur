from __future__ import annotations
import asyncio
import math
import os
import random
import re as _re
from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth as _Stealth

_stealth = _Stealth()

# Kept alive for the process lifetime when headed mode starts Xvfb automatically.
_virtual_display = None


class CloudflareBlockedError(Exception):
    pass


_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]

_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]
    _ua_index += 1
    return ua


_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['fr-BE','fr','en-US','en']});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'permissions', {
    get: () => ({query: (p) => Promise.resolve({state: p.name === 'notifications' ? 'denied' : 'granted'})})
});
"""


async def new_browser(lang: str = "fr-BE", headed: bool = False) -> Browser:
    global _virtual_display

    # Headed mode on a server with no display (Xvfb virtual framebuffer).
    # Falls back gracefully if pyvirtualdisplay isn't installed — use
    # `xvfb-run -a uv run python <script>` as the manual fallback in that case.
    if headed and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            _virtual_display = Display(visible=False, size=(1920, 1080))
            _virtual_display.start()
        except Exception:
            pass  # xvfb-run fallback

    p = await async_playwright().start()
    args = [
        "--no-sandbox",
        f"--lang={lang}",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not headed:
        args += ["--disable-gpu", "--disable-extensions"]

    # Residential proxy — required for Takeaway (CF clears to the exit IP).
    # PROXY_STICKY_SESSION must be a stable session ID so the exit IP never
    # rotates mid-run (CF binds its clearance cookie to the IP it issued it to).
    # Sticky-session username format is provider-specific; common formats:
    #   Brightdata / Oxylabs:  "{username}-sessid-{session_id}"
    #   Smartproxy:            "{username}-session-{session_id}"
    # Adjust the f-string below to match your provider.
    proxy = None
    proxy_server = os.environ.get("PROXY_SERVER")
    if proxy_server:
        username = os.environ.get("PROXY_USERNAME", "")
        password = os.environ.get("PROXY_PASSWORD", "")
        sticky = os.environ.get("PROXY_STICKY_SESSION", "")
        if sticky:
            username = f"{username}-sessid-{sticky}"  # ← adjust format here
        proxy = {"server": proxy_server, "username": username, "password": password}

    browser = await p.chromium.launch(headless=not headed, args=args, proxy=proxy)
    return browser


async def new_page(browser: Browser, lang: str = "fr-BE") -> Page:
    context = await browser.new_context(
        user_agent=_next_ua(),
        locale=lang,
        timezone_id="Europe/Brussels",  # matches Belgian exit IP; mismatch = CF flag
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={"Accept-Language": f"{lang},{lang[:2]};q=0.9,en;q=0.8"},
        java_script_enabled=True,
        bypass_csp=True,
    )
    await context.add_init_script(_STEALTH_SCRIPT)
    page = await context.new_page()
    await _stealth.apply_stealth_async(page)
    return page


async def _move_mouse_human(page: Page, x: float, y: float) -> None:
    """Move mouse to (x, y) in a curved, non-linear path with random speed."""
    cur_x, cur_y = random.uniform(100, 800), random.uniform(100, 600)
    steps = random.randint(18, 35)
    for i in range(steps + 1):
        t = i / steps
        # ease-in-out + slight sine wobble
        eased = t * t * (3 - 2 * t)
        wobble_x = math.sin(t * math.pi * random.uniform(1.5, 3.5)) * random.uniform(4, 14)
        wobble_y = math.cos(t * math.pi * random.uniform(1.5, 3.5)) * random.uniform(4, 14)
        mx = cur_x + (x - cur_x) * eased + wobble_x
        my = cur_y + (y - cur_y) * eased + wobble_y
        await page.mouse.move(mx, my)
        await asyncio.sleep(random.uniform(0.01, 0.045))


async def wait_for_cf_clear(page: Page, timeout_s: int = 90) -> bool:
    """Wait for CF challenge to pass, moving mouse naturally. Returns True if cleared."""
    vw, vh = 1920, 1080
    deadline = timeout_s * 2  # iterations of 0.5s each

    for tick in range(deadline):
        # CF reloads/navigates the page mid-challenge; any of these calls can
        # race with that navigation and throw "Execution context was destroyed".
        # Swallow and retry next tick instead of crashing the whole scrape.
        try:
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                return True

            # Every ~2s do a random mouse move; occasionally scroll a tiny bit
            if tick % 4 == 0:
                tx = random.uniform(vw * 0.1, vw * 0.85)
                ty = random.uniform(vh * 0.1, vh * 0.75)
                await _move_mouse_human(page, tx, ty)

            if tick % 12 == 6:
                scroll = random.randint(30, 120)
                await page.evaluate(f"window.scrollBy(0, {scroll})")
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.evaluate(f"window.scrollBy(0, -{scroll})")
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.4, 0.6))

    return False


def check_cloudflare(title: str) -> None:
    lower = title.lower()
    if "just a moment" in lower or "cloudflare" in lower:
        raise CloudflareBlockedError("Cloudflare challenge detected")


def noop_log(line: str) -> None:
    pass


def parse_menu_price(val: str | float | int | None, *, is_cents: bool = False) -> float | None:
    """Parse price from various formats to float EUR.

    is_cents=True for UberEats priceDoubleCents (integer cents).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if is_cents:
            return round(val / 100, 2)
        return float(val)
    low = str(val).lower()
    if any(w in low for w in ("gratuit", "free", "gratis", "0,00", "0.00")):
        return 0.0
    m = _re.search(r"(\d+)[,.](\d{2})", str(val))
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _re.search(r"(\d+)", str(val))
    return float(m.group(1)) if m else None
