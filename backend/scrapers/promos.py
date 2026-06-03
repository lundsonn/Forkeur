"""Shared promotion-parsing utilities for all platform scrapers."""
from __future__ import annotations
import re


def extract_min_order(text: str) -> float | None:
    """Parse the minimum spend amount from a promotion text (FR/DE/EN)."""
    low = text.lower()
    patterns = [
        r"spend\s+€\s*(\d+(?:[,.]\d+)?)",
        r"zahle\s+(\d+(?:[,.]\d+)?)\s*€",
        r"\(zahle\s+(\d+(?:[,.]\d+)?)(?:\s*€)?\)",
        r"ab einem warenwert von\s+(\d+(?:[,.]\d+)?)\s*€",
        r"(?:dès|à partir de)\s+(\d+(?:[,.]\d+)?)\s*€",
        r"(?:pour|for).{0,20}(?:≥|>=|>|de)\s*€?\s*(\d+(?:[,.]\d+)?)",
        r"(?:min|minimum)[.:\s]+€?\s*(\d+(?:[,.]\d+)?)",
        r"(?:commande|order) (?:de |d'au moins |of |minimum )?€?\s*(\d+(?:[,.]\d+)?)",
        r"(\d+(?:[,.]\d+)?)\s*€(?:\s+d'achat|\s+minimum|\s+min\.?)?$",
    ]
    for pat in patterns:
        m = re.search(pat, low)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def classify_promo(text: str) -> dict:
    """Classify a promotion label (FR/DE/EN) into a structured dict.

    Returns: {promo_type, label, value, min_order}
    """
    low = text.lower()

    # Free delivery
    if re.search(
        r"€0 delivery|livraison (gratuite|offerte)|gratis (levering|lieferung)|"
        r"free delivery|kostenlose lieferung|get €0 delivery|0\s*€ (de livraison|livraison)|"
        r"livraison.{0,30}gratuite|delivery.{0,20}free|gratuite.{0,20}livraison",
        low,
    ):
        return {"promo_type": "free_delivery", "label": text,
                "value": 0.0, "min_order": extract_min_order(low)}

    # BOGO — buy one get one
    if re.search(
        r"buy 1.{0,8}get 1|1 (achet|plat achet).{0,8}(offert|gratuit)|kaufe 1.{0,8}(gratis|kostenlos)|"
        r"get 1 free|1 kostenlos|erhalte 1|2 (for|pour) (1|un)|2-for-1",
        low,
    ):
        return {"promo_type": "bogo", "label": text,
                "value": None, "min_order": extract_min_order(low)}

    # Free item
    if re.search(
        r"free item|article offert|produit offert|kostenloser artikel|"
        r"add a free item|gratis artikel|offert dès|1 (article|produit) (offert|gratuit)|"
        r"item offert|free article",
        low,
    ):
        return {"promo_type": "free_item", "label": text,
                "value": None, "min_order": extract_min_order(low)}

    # Percentage discount
    m = re.search(r"(\d+)\s*%", low)
    if m:
        return {"promo_type": "pct_discount", "label": text,
                "value": float(m.group(1)), "min_order": extract_min_order(low)}

    # Absolute discount
    m = re.search(
        r"(?:spare|save|économise[zr]?|remise de|rabatt)\s+(?:€\s*)?(\d+(?:[,.]\d+)?)(?:\s*€)?",
        low,
    )
    if m:
        val = float(m.group(1).replace(",", "."))
        return {"promo_type": "abs_discount", "label": text,
                "value": val, "min_order": extract_min_order(low)}

    # Spend threshold
    if re.search(r"^spend\s+€|^zahle\s+\d|^dépense|^besteed", low):
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
