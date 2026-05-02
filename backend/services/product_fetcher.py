"""
ProductFetcher — resolves an ASIN to a Product object.

Resolution order:
  1. Amazon page scrape (httpx + BeautifulSoup)
  2. Rainforest API fallback
  3. Stub with brand="MANUAL_ENTRY_REQUIRED"
"""

from __future__ import annotations
import os, re, asyncio
from functools import lru_cache
import httpx
from bs4 import BeautifulSoup
from models import Product

_STUB_CATEGORY = "Health & Household"
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _extract_asin(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"(?:/dp/|/gp/product/)([A-Z0-9]{10})", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Z0-9]{10}", raw):
        return raw
    raise ValueError(f"Could not parse ASIN from: {raw!r}")


async def _scrape_amazon(asin: str) -> Product | None:
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": _USER_AGENTS[hash(asin) % len(_USER_AGENTS)],
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one("#productTitle")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    brand = ""
    brand_el = soup.select_one("#bylineInfo")
    if brand_el:
        brand_text = brand_el.get_text(strip=True)
        for prefix in ("Brand: ", "Visit the ", " Store", "by "):
            brand_text = brand_text.replace(prefix, "").strip()
        brand = brand_text
    if not brand:
        for row in soup.select("#productDetails_techSpec_section_1 tr, #detailBullets_feature_div li"):
            text = row.get_text(" ", strip=True)
            if "Brand" in text:
                parts = text.split("Brand")
                if len(parts) > 1:
                    brand = parts[1].strip().lstrip(":").strip()
                    break
    if not brand:
        brand = "Unknown Brand"

    category = _STUB_CATEGORY
    breadcrumb = soup.select("#wayfinding-breadcrumbs_feature_div a")
    if breadcrumb:
        crumbs = [el.get_text(strip=True) for el in breadcrumb]
        crumbs = [c for c in crumbs if c and c.lower() not in ("all departments",)]
        if crumbs:
            category = crumbs[0]

    bullets: list[str] = []
    for li in soup.select("#feature-bullets ul li span.a-list-item"):
        text = li.get_text(strip=True)
        if text and len(text) > 10:
            bullets.append(text)

    image_url: str | None = None
    img_el = soup.select_one("#imgTagWrapperId img, #landingImage")
    if img_el:
        image_url = img_el.get("src") or img_el.get("data-old-hires")

    return Product(asin=asin, brand=brand, title=title, category=category,
                   bullets=bullets[:10], image_url=image_url)


@lru_cache(maxsize=128)
def _fetch_rainforest_sync(asin: str) -> dict:
    api_key = os.environ.get("RAINFOREST_API_KEY", "")
    if not api_key:
        raise RuntimeError("RAINFOREST_API_KEY not set")
    params = {"api_key": api_key, "type": "product", "asin": asin, "amazon_domain": "amazon.com"}
    with httpx.Client(timeout=15) as client:
        resp = client.get("https://api.rainforestapi.com/request", params=params)
        resp.raise_for_status()
        return resp.json()


async def _try_rainforest(asin: str) -> Product | None:
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_rainforest_sync, asin)
        prod = data.get("product", {})
        if not prod:
            return None
        title = prod.get("title", "")
        if not title or "staging" in title.lower():
            return None
        brand = prod.get("brand") or (prod.get("brand_link") or {}).get("title") or "Unknown Brand"
        category = ((prod.get("categories") or [{}])[0]).get("name") or _STUB_CATEGORY
        bullets = prod.get("feature_bullets", [])
        image_url = (prod.get("main_image") or {}).get("link")
        return Product(asin=asin, brand=brand, title=title, category=category,
                       bullets=bullets[:10], image_url=image_url)
    except Exception:
        return None


async def fetch_product(raw_input: str, manual_brand: str | None = None,
                        manual_title: str | None = None) -> Product:
    if manual_brand and manual_title:
        try:
            asin = _extract_asin(raw_input)
        except ValueError:
            asin = raw_input
        return Product(asin=asin, brand=manual_brand, title=manual_title, category=_STUB_CATEGORY)

    try:
        asin = _extract_asin(raw_input)
    except ValueError:
        return Product(asin=raw_input, brand="MANUAL_ENTRY_REQUIRED",
                       title=raw_input, category=_STUB_CATEGORY)

    product = await _scrape_amazon(asin)
    if product and product.brand != "Unknown Brand":
        return product

    rf = await _try_rainforest(asin)
    if rf:
        return rf

    if product:
        return product

    return Product(asin=asin, brand="MANUAL_ENTRY_REQUIRED",
                   title=f"Product {asin}", category=_STUB_CATEGORY)
