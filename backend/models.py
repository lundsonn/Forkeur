from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel
from constants import DEFAULT_ADDRESS


# ── Scraper interface ──────────────────────────────────────────────────────────

@dataclass
class ScraperConfig:
    address: str = None
    
    def __post_init__(self):
        if self.address is None:
            self.address = DEFAULT_ADDRESS
    target: str | None = None
    max_items: int | None = None  # None = no cap (full run); set to 10 for test mode
    scrape_menus: bool = False
    max_menus: int = 3
    listing_only: bool = False  # skip Phase 2 (menu scraping); counts only


@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict] = field(default_factory=list)
    menu_items_saved: int = 0


# ── API request models ─────────────────────────────────────────────────────────

class RunTriggerIn(BaseModel):
    scrape_menus: bool = False
    max_menus: int = 3
    test_mode: bool = False  # True caps at 10 items; False = full run
    target: str | None = None  # passthrough hint (e.g. "dry-run" for the match job)


# ── API response models ────────────────────────────────────────────────────────

class ScraperRunOut(BaseModel):
    id: str
    platform: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    records_saved: int = 0
    error_msg: str | None = None


class ScraperStatusOut(BaseModel):
    platform: str
    status: str        # "idle" | "running" | "success" | "failed" | "blocked"
    last_run: ScraperRunOut | None = None


class ScheduleConfigIn(BaseModel):
    platform: str
    cron: str          # e.g. "0 */6 * * *"
    enabled: bool = True


class ScheduleConfigOut(ScheduleConfigIn):
    next_run: datetime | None = None


class RestaurantOut(BaseModel):
    id: str
    name: str
    slug: str
    cuisine: str | None = None
    neighborhood: str | None = None
    is_chain: bool = False


class MenuItemOut(BaseModel):
    id: str
    listing_id: str
    title: str
    price: float | None = None
    catalog_name: str | None = None


class RunTriggerOut(BaseModel):
    run_id: str
