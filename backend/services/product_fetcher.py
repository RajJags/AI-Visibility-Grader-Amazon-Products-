"""
ProductFetcher — resolves an ASIN to a Product.

Resolution order:
  1. Rainforest API  (if RAINFOREST_API_KEY is set — reliable on any server)
  2. Amazon page scrape  (works locally; often blocked on cloud IPs)
  3. Stub → frontend shows manual-entry form (HTTP 422)

On Render/cloud environments Amazon almost always blocks the scrape,
so Rainforest is tried first to avoid a 15-second timeout on every call.
"""

from __future__ import annotations
import os, re, asyncio
import httpx
from bs4 import BeautifulSoup
from models import Product

_STUB_CATEGORY = "Health & Household"
_IS_CLOUD = bool(os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT")
                 or os.environ.get("FLY_APP_NAME") or os.environ.get("DYNO"))

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _extract_asin(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"(?:/dp/|/gp/product/)([A-Z0-9]{10})", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Z0-9]{10}", raw):
        return raw
    raise ValueError(f"Could not parse ASIN from: {raw!r}")


# ── Rainforest ────────────────────────────────────────────────────────────────

def _fetch_rainforest_sync(asin: str) -> dict:
    api_key = os.environ.get("RAINFOREST_API_KEY", "")
    if not api_key:
        raise RuntimeError("RAINFOREST_API_KEY not set")
    params = {"api_key": api_key, "type": "product", "asin": asin,
              "amazon_domain": "amazon.com"}
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
        brand = (prod.get("brand")
                 or (prod.get("brand_link") or {}).get("title")
                 or "Unknown Brand")
        category = ((prod.get("categories") or [{}])[0]).get("name") or _STUB_CATEGORY
        bullets = prod.get("feature_bullets", []) or []
        image_url = (prod.get("main_image") or {}).get("link")
        return Product(asin=asin, brand=brand, title=title, category=category,
                       bullets=bullets[:10], image_url=image_url)
    except Exception:
        return None


# ── Amazon scrape ─────────────────────────────────────────────────────────────

async def _scrape_amazon(asin: str) -> Product | None:
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": _USER_AGENTS[hash(asin) % len(_USER_AGENTS)],
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10,
                                     headers=headers) as client:
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
        return None  # got a CAPTCHA or bot-check page

    brand = ""
    brand_el = soup.select_one("#bylineInfo")
    if brand_el:
        txt = brand_el.get_text(strip=True)
        for pfx in ("Brand: ", "Visit the ", " Store", "by "):
            txt = txt.replace(pfx, "").strip()
        brand = txt
    if not brand:
        for row in soup.select(
            "#productDetails_techSpec_section_1 tr, #detailBullets_feature_div li"
        ):
            text = row.get_text(" ", strip=True)
            if "Brand" in text:
                parts = text.split("Brand")
                if len(parts) > 1:
                    brand = parts[1].strip().lstrip(":").strip()
                    break
    brand = brand or "Unknown Brand"

    category = _STUB_CATEGORY
    crumbs = soup.select("#wayfinding-breadcrumbs_feature_div a")
    if crumbs:
        names = [el.get_text(strip=True) for el in crumbs
                 if el.get_text(strip=True).lower() != "all departments"]
        if names:
            category = names[0]

    bullets = [
        li.get_text(strip=True)
        for li in soup.select("#feature-bullets ul li span.a-list-item")
        if len(li.get_text(strip=True)) > 10
    ]

    img = soup.select_one("#imgTagWrapperId img, #landingImage")
    image_url = (img.get("src") or img.get("data-old-hires")) if img else None

    return Product(asin=asin, brand=brand, title=title, category=category,
                   bullets=bullets[:10], image_url=image_url)


# ── Public entry point ────────────────────────────────────────────────────────

async def fetch_product(raw_input: str, manual_brand: str | None = None,
                        manual_title: str | None = None) -> Product:
    # Manual override — skip all fetching
    if manual_brand and manual_title:
        try:
            asin = _extract_asin(raw_input)
        except ValueError:
            asin = raw_input
        return Product(asin=asin, brand=manual_brand, title=manual_title,
                       category=_STUB_CATEGORY, bullets=[], image_url=None)

    try:
        asin = _extract_asin(raw_input)
    except ValueError:
        return Product(asin=raw_input, brand="MANUAL_ENTRY_REQUIRED",
                       title=raw_input, category=_STUB_CATEGORY,
                       bullets=[], image_url=None)

    # On cloud: Rainforest first (Amazon always blocks); locally: scrape first
    if _IS_CLOUD:
        product = await _try_rainforest(asin) or await _scrape_amazon(asin)
    else:
        scraped = await _scrape_amazon(asin)
        product = scraped if (scraped and scraped.brand != "Unknown Brand") else None
        product = product or await _try_rainforest(asin) or scraped

    if product:
        return product

    return Product(asin=asin, brand="MANUAL_ENTRY_REQUIRED",
                   title=f"Product {asin}", category=_STUB_CATEGORY,
                   bullets=[], image_url=None)


async def fetch_product_with_llm_fallback(
    raw_input: str,
    manual_brand: str | None = None,
    manual_title: str | None = None,
) -> Product:
    """
    Same as fetch_product but if MANUAL_ENTRY_REQUIRED is returned,
    asks an LLM to infer brand/title from the ASIN as a last resort.
    Only used when the user hasn't provided manual details.
    """
    from llm_clients import GenerationClient

    product = await fetch_product(raw_input, manual_brand, manual_title)
    if product.brand != "MANUAL_ENTRY_REQUIRED":
        return product

    # LLM last resort: infer from ASIN
    try:
        client = GenerationClient()
        asin = product.asin
        raw = await client.query(
            f"What Amazon product has ASIN {asin}? "
            "Reply with exactly two lines:\nBrand: <brand name>\nTitle: <full product title>\n"
            "If you don't know, write Unknown for both.",
            system="You are a product database assistant. Be concise and accurate.",
        )
        brand, title = "Unknown Brand", f"Product {asin}"
        for line in raw.strip().splitlines():
            if line.lower().startswith("brand:"):
                brand = line.split(":", 1)[1].strip()
            elif line.lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
        if brand.lower() not in ("unknown", "unknown brand", ""):
            return Product(asin=asin, brand=brand, title=title,
                           category=_STUB_CATEGORY, bullets=[], image_url=None)
    except Exception:
        pass

    return product  # still MANUAL_ENTRY_REQUIRED → frontend shows manual form
