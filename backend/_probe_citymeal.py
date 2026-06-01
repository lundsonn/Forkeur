"""
Probe citymeal.com Android API for Takeaway.com restaurant + menu data.

Endpoint: POST https://citymeal.com/android/android.php
Signing:  MD5(var1+var2+...+varN + "4ndro1d") -> var0
Response: XML

Run:
    cd backend && uv run python _probe_citymeal.py
"""
from __future__ import annotations
import asyncio
import hashlib
import httpx
import xml.etree.ElementTree as ET

BASE_URL = "https://www.citymeal.com/android/android.php"
SALT = "4ndro1d"

# Brussels centre
POSTAL_CODE = "1000"
COUNTRY_CODE = "be"
LAT = "50.8503"
LON = "4.3517"
LANGUAGE = "fr"


def _sign(*args: str) -> str:
    payload = "".join(args) + SALT
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _build_params(method: str, *args: str) -> dict:
    vars = {"var1": method}
    for i, arg in enumerate(args, start=2):
        vars[f"var{i}"] = arg
    vars["var0"] = _sign(method, *args)
    vars["version"] = "5.7"
    vars["systemversion"] = "24"
    vars["appname"] = "Takeaway.com"
    vars["language"] = LANGUAGE
    return vars


def _xml_to_dict(element: ET.Element, depth: int = 0) -> dict | str:
    if len(element) == 0:
        return element.text or ""
    return {child.tag: _xml_to_dict(child, depth + 1) for child in element}


async def call(client: httpx.AsyncClient, method: str, *args: str) -> ET.Element | None:
    params = _build_params(method, *args)
    print(f"\n→ {method}({', '.join(repr(a) for a in args)})")
    print(f"  var0 (sig): {params['var0']}")
    try:
        r = await client.post(BASE_URL, data=params, timeout=30)
        print(f"  HTTP {r.status_code}  len={len(r.content)}")
        if r.status_code != 200:
            print(f"  ERROR body: {r.text[:300]}")
            return None
        if not r.content:
            print("  EMPTY response")
            return None
        root = ET.fromstring(r.content)
        return root
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return None


def print_xml(root: ET.Element, indent: int = 0) -> None:
    tag = root.tag
    text = (root.text or "").strip()
    attrs = root.attrib
    prefix = "  " * indent
    if len(root) == 0:
        print(f"{prefix}<{tag}{' ' + str(attrs) if attrs else ''}> = {text!r}")
    else:
        print(f"{prefix}<{tag}{' ' + str(attrs) if attrs else ''}>")
        for child in root:
            print_xml(child, indent + 1)


async def main() -> None:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Takeaway.com/5.7 (Android; 24)",
        "Accept": "application/xml, text/xml, */*",
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:

        # 0. Simplest possible call — no args, tests signing works
        print("=" * 60)
        print("TEST 0: getcountriesdata (no args)")
        root0 = await call(client, "getcountriesdata")
        if root0 is not None:
            print(f"  Top-level tag: {root0.tag}")
            print(f"  Children: {[c.tag for c in list(root0)[:5]]}")
            print("  Raw XML (first 1500 chars):")
            print(ET.tostring(root0, encoding="unicode")[:1500])
        else:
            # Try without version/systemversion to isolate issue
            print("  Retrying bare (no version fields)...")
            params_bare = _build_params("getcountriesdata")
            params_bare.pop("version", None)
            params_bare.pop("systemversion", None)
            params_bare.pop("appname", None)
            params_bare.pop("language", None)
            print(f"  params: {params_bare}")
            try:
                r = await client.post(BASE_URL, data=params_bare, timeout=30)
                print(f"  HTTP {r.status_code}  len={len(r.content)}  body: {r.text[:500]}")
            except Exception as e:
                print(f"  EXCEPTION: {e}")

        # 1. Get restaurants by postal code + geolocation
        print("\n" + "=" * 60)
        print("TEST 1: getrestaurants")
        root = await call(client, "getrestaurants", POSTAL_CODE, COUNTRY_CODE, LAT, LON, LANGUAGE)
        if root is not None:
            restaurants = root.findall(".//restaurant") or root.findall(".//item") or list(root)
            print(f"  Top-level children: {[c.tag for c in root[:5]]}")
            print(f"  Restaurant-like nodes: {len(restaurants)}")
            if restaurants:
                first = restaurants[0]
                print("  First restaurant:")
                print_xml(first, indent=2)
                rid = first.findtext("restaurantid") or first.findtext("id") or first.get("id") or ""
                slug = first.findtext("name") or ""
                print(f"\n  → restaurantId={rid!r}  name={slug!r}")
            else:
                print("  Raw XML (first 2000 chars):")
                print(ET.tostring(root, encoding="unicode")[:2000])
        else:
            # Try NL as fallback to see if BE is the issue
            print("  Retrying with NL / 1000AB Amsterdam...")
            root_nl = await call(client, "getrestaurants", "1000AB", "nl", "52.3702", "4.8952", "nl")
            if root_nl is not None:
                print("  NL works! BE endpoint may be region-gated.")
                print(ET.tostring(root_nl, encoding="unicode")[:500])

        # 2. getdatafromgeolocation
        print("\n" + "=" * 60)
        print("TEST 2: getdatafromgeolocation")
        root2 = await call(client, "getdatafromgeolocation", LAT, LON, COUNTRY_CODE)
        if root2 is not None:
            print(f"  Top-level children: {[c.tag for c in root2[:5]]}")
            print("  Raw XML (first 1000 chars):")
            print(ET.tostring(root2, encoding="unicode")[:1000])

        # 3. getrestaurantdata — use first restaurant id if found
        if root is not None:
            restaurants = root.findall(".//restaurant") or list(root)
            if restaurants:
                first = restaurants[0]
                rid = (
                    first.findtext("restaurantid")
                    or first.findtext("id")
                    or first.get("id")
                    or ""
                )
                if rid:
                    print("\n" + "=" * 60)
                    print(f"TEST 3: getrestaurantdata (id={rid!r})")
                    root3 = await call(
                        client, "getrestaurantdata",
                        rid, POSTAL_CODE, "1", LAT, LON, ""
                    )
                    if root3 is not None:
                        menu_items = (
                            root3.findall(".//menuitem")
                            or root3.findall(".//product")
                            or root3.findall(".//item")
                        )
                        print(f"  Menu item nodes: {len(menu_items)}")
                        if menu_items:
                            print("  First 3 items:")
                            for item in menu_items[:3]:
                                print_xml(item, indent=2)
                        else:
                            print("  Raw XML (first 2000 chars):")
                            print(ET.tostring(root3, encoding="unicode")[:2000])


if __name__ == "__main__":
    asyncio.run(main())
