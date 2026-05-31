from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel


# ── Scraper interface ──────────────────────────────────────────────────────────

@dataclass
class ScraperConfig:
    address: str = "Pl. Poelaert 1, 1000 Bruxelles"
    target: str | None = None
    max_items: int = 50
    scrape_menus: bool = False
    max_menus: int = 3


@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict] = field(default_factory=list)
    menu_items_saved: int = 0


# ── API request models ─────────────────────────────────────────────────────────

class RunTriggerIn(BaseModel):
    scrape_menus: bool = False
    max_menus: int = 3


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


class MenuItemOut(BaseModel):
    id: str
    listing_id: str
    title: str
    price: float | None = None
    catalog_name: str | None = None


class RunTriggerOut(BaseModel):
    run_id: str
