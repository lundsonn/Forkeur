"""_is_junk guards against Deliveroo promo/ETA tiles scraped as restaurant names."""
import db


JUNK = [
    "Environ 25 min", "Environ 15 min", "Environ 40 min",
    "Profitez de -\u202A10 %\u202C", "Profitez de -\u202A50 %\u202C",
    "1 plat acheté = 1 plat offert", "Around 20 min",
    "Pré-commande 30", "-10%", "50% off",
]
REAL = [
    "Pizza Hut Delivery", "Poké Delivery", "Sushi Delivery",
    "La Pazza Gioia Takeaway & Delivery", "Mr Cod",
    "Pasta Express Etterbeek", "10 Barrels", "Café 50", "Resto 1080",
]


def test_junk_names_rejected():
    for name in JUNK:
        assert db._is_junk(name), f"should be junk: {name!r}"


def test_real_names_kept():
    for name in REAL:
        assert not db._is_junk(name), f"should be real: {name!r}"
