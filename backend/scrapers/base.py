from __future__ import annotations
import asyncio
import math
import os
import random
import re as _re
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth as _Stealth

_stealth = _Stealth()

# Kept alive for the process lifetime when headed mode starts Xvfb automatically.
_virtual_display = None


class CloudflareBlockedError(Exception):
    pass


_SSRF_BLOCKLIST = _re.compile(
    r'localhost|127\.|0\.0\.0\.0|169\.254\.|10\.\d+\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.'
    r'|\.internal$|\.local$|oast\.|interactsh\.|burpcollaborator\.|canarytokens\.',
    _re.IGNORECASE,
)


def is_safe_url(url: str) -> bool:
    """Return True only if the URL is http/https and does not point at internal infrastructure."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.netloc.lower().split(":")[0]
    if not host or "." not in host:
        return False
    return not bool(_SSRF_BLOCKLIST.search(host))


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
        "--window-size=1280,800",      # smaller framebuffer; was 1920x1080
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--js-flags=--max-old-space-size=512",  # cap V8 heap per renderer (default ~1.4 GB)
        "--disk-cache-size=1",                  # kill HTTP cache in network process
        "--media-cache-size=1",
        "--disable-backgrounding-occluded-windows",  # prevent renderer throttling when off-screen
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


async def new_page(browser: Browser, lang: str = "fr-BE", block_media: bool = True) -> Page:
    context = await browser.new_context(
        user_agent=_next_ua(),
        locale=lang,
        timezone_id="Europe/Brussels",  # matches Belgian exit IP; mismatch = CF flag
        viewport={"width": 1280, "height": 800},
        extra_http_headers={"Accept-Language": f"{lang},{lang[:2]};q=0.9,en;q=0.8"},
        java_script_enabled=True,
        bypass_csp=True,
    )
    await context.add_init_script(_STEALTH_SCRIPT)
    page = await context.new_page()
    await _stealth.apply_stealth_async(page)
    if block_media:
        # Images and media are not needed for data scraping and are the biggest
        # contributors to renderer RSS and the network-service process cache.
        await page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media"}
            else route.continue_(),
        )
    return page


async def new_sibling_page(page: Page, block_media: bool = True) -> Page:
    """Open another page in the SAME browser context as `page`.

    Sibling pages share cookies, localStorage and network state, so they inherit
    a delivery-address session (e.g. UberEats location set during address entry)
    that a fresh `new_page()` context would not have. Used to parallelize menu
    scraping across N pages while staying inside the one trusted session.
    """
    sib = await page.context.new_page()
    await _stealth.apply_stealth_async(sib)
    if block_media:
        await sib.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media"}
            else route.continue_(),
        )
    return sib


async def _move_mouse_human(page: Page, x: float, y: float) -> None:
    """Move mouse to (x, y) in a curved, non-linear path with random speed."""
    cur_x, cur_y = random.uniform(100, 800), random.uniform(100, 600)
    steps = random.randint(8, 15)
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
                # Brief pause to confirm CF didn't re-fire immediately after clearing
                await asyncio.sleep(1.5)
                title2 = await page.title()
                if "instant" not in title2.lower() and "moment" not in title2.lower():
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


# ── Shared browser singleton ─────────────────────────────────────────────────
# All headless scrapers share one Chromium process. Each gets an isolated
# context (cookies, storage, network state). Their asyncio.sleep() / wait_for*
# gaps interleave in the event loop so the total wall time collapses to the
# slowest scraper rather than the sum.
# Headed scrapers (takeaway) always get a private browser — can't mix flags.

_shared_browser: Browser | None = None
_browser_refcount: int = 0
_browser_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    return _browser_lock


@asynccontextmanager
async def browser_session(lang: str = "fr-BE", headed: bool = False):
    """Async context manager yielding a browser.

    Headless: returns (or creates) the shared browser, ref-counted.
              Closes the browser when the last user exits.
    Headed:   always creates a private browser; closes it on exit.
    """
    global _shared_browser, _browser_refcount

    if headed:
        browser = await new_browser(lang=lang, headed=True)
        try:
            yield browser
        finally:
            try:
                await browser.close()
            except Exception:
                pass
        return

    lock = _get_lock()
    async with lock:
        if _shared_browser is None or not _shared_browser.is_connected():
            _shared_browser = await new_browser(lang=lang, headed=False)
            _browser_refcount = 0
        _browser_refcount += 1

    try:
        yield _shared_browser
    finally:
        async with lock:
            _browser_refcount -= 1
            if _browser_refcount <= 0 and _shared_browser is not None:
                try:
                    await _shared_browser.close()
                except Exception:
                    pass
                _shared_browser = None
                _browser_refcount = 0


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
