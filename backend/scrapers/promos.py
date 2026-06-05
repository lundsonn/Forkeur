"""Shared promotion-parsing utilities for all platform scrapers."""
from __future__ import annotations
import re

# Compiled once at import time — classify_promo is called O(listings × promos) per scrape.
_MIN_ORDER_PATTERNS = [
    re.compile(r"orders?\s+(?:over|above|of)\s+[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"orders?\s+[€$£]\s*(\d+(?:[,.]\d+)?)\s*\+"),
    re.compile(r"(?:dès|à partir de)\s+[€$£]?\s*(\d+(?:[,.]\d+)?)(?:\s*[€$£])?"),
    re.compile(r"vanaf\s+[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"ab\s+(?:einem\s+warenwert\s+von\s+)?[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"spend\s+[€$£]\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"\(?zahle\s+(\d+(?:[,.]\d+)?)(?:\s*[€$£])?\)?"),
    re.compile(r"(?:pour|for).{0,20}(?:≥|>=|>|de)\s*[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"(?:min|minimum)[.:\s]+[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"(?:commande|order)\s+(?:de\s+|d'au moins\s+|of\s+|minimum\s+)?[€$£]?\s*(\d+(?:[,.]\d+)?)"),
    re.compile(r"(\d+(?:[,.]\d+)?)\s*[€$£](?:\s+d'achat|\s+minimum|\s+min\.?)?$"),
]

_FREE_DELIVERY_RE = re.compile(
    r"€0 delivery|livraison (gratuite|offerte)|gratis (levering|lieferung)|"
    r"free delivery|kostenlose lieferung|get €0 delivery|0\s*€ (de livraison|livraison)|"
    r"livraison.{0,30}gratuite|delivery.{0,20}free|gratuite.{0,20}livraison"
)
_BOGO_RE = re.compile(
    r"buy 1.{0,8}get 1|1 (achet|plat achet).{0,8}(offert|gratuit)|kaufe 1.{0,8}(gratis|kostenlos)|"
    r"get 1 free|1 kostenlos|erhalte 1|2 (for|pour) (1|un)|2-for-1"
)
_FREE_ITEM_RE = re.compile(
    r"free item|article offert|produit offert|kostenloser artikel|"
    r"add a free item|gratis artikel|offert dès|1 (article|produit) (offert|gratuit)|"
    r"item offert|free article"
)
_PCT_RE = re.compile(r"(\d+)\s*%")
_ABS_RE = re.compile(
    r"(?:spare|save|économise[zr]?|remise de|rabatt)\s+(?:€\s*)?(\d+(?:[,.]\d+)?)(?:\s*€)?"
)
_SPEND_RE = re.compile(r"^spend\s+€|^zahle\s+\d|^dépense|^besteed")


def extract_min_order(text: str) -> float | None:
    """Parse the minimum spend amount from a promotion text (FR/NL/DE/EN)."""
    for pat in _MIN_ORDER_PATTERNS:
        m = pat.search(text)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def classify_promo(text: str) -> dict:
    """Classify a promotion label (FR/DE/EN) into a structured dict.

    Returns: {promo_type, label, value, min_order}
    """
    low = text.lower()

    if _FREE_DELIVERY_RE.search(low):
        return {"promo_type": "free_delivery", "label": text,
                "value": 0.0, "min_order": extract_min_order(low)}

    if _BOGO_RE.search(low):
        return {"promo_type": "bogo", "label": text,
                "value": None, "min_order": extract_min_order(low)}

    if _FREE_ITEM_RE.search(low):
        return {"promo_type": "free_item", "label": text,
                "value": None, "min_order": extract_min_order(low)}

    m = _PCT_RE.search(low)
    if m:
        return {"promo_type": "pct_discount", "label": text,
                "value": float(m.group(1)), "min_order": extract_min_order(low)}

    m = _ABS_RE.search(low)
    if m:
        val = float(m.group(1).replace(",", "."))
        return {"promo_type": "abs_discount", "label": text,
                "value": val, "min_order": extract_min_order(low)}

    if _SPEND_RE.search(low):
        return {"promo_type": "spend_save", "label": text,
                "value": None, "min_order": extract_min_order(low)}

    return {"promo_type": "other", "label": text, "value": None, "min_order": None}


def parse_promo_texts(texts: list[str]) -> list[dict]:
    """Classify and deduplicate a list of raw promotion labels."""
    seen: set[str] = set()
    result: list[dict] = []
    for text in texts:
        text = text.strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        result.append(classify_promo(text))
    return result
