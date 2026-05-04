"""
ProductFetcher  -  resolves an ASIN to a Product.

Resolution order:
  1. Rainforest API  (if RAINFOREST_API_KEY is set  -  reliable on any server)
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

    # lxml is faster but not always available; fall back to built-in html.parser
    _parser = "lxml"
    try:
        import lxml  # noqa: F401
    except ImportError:
        _parser = "html.parser"
    soup = BeautifulSoup(html, _parser)
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




async def _try_rainforest_search(brand: str, title: str) -> Product | None:
    """Use Rainforest search endpoint to find the best-matching product."""
    api_key = os.environ.get('RAINFOREST_API_KEY', '')
    if not api_key:
        return None
    try:
        loop = asyncio.get_event_loop()
        def _call():
            params = {
                'api_key': api_key,
                'type': 'search',
                'amazon_domain': 'amazon.com',
                'search_term': f'{brand} {title}',
            }
            with httpx.Client(timeout=12) as client:
                resp = client.get('https://api.rainforestapi.com/request', params=params)
                resp.raise_for_status()
                return resp.json()
        data = await loop.run_in_executor(None, _call)
        results = data.get('search_results', [])
        if not results:
            return None
        top = results[0]
        asin = top.get('asin', '')
        if not asin:
            return None
        # Now fetch the full product page
        return await _try_rainforest(asin)
    except Exception:
        return None

# ── Amazon search by brand+title ──────────────────────────────────────────────

async def _search_and_fetch(brand: str, title: str) -> Product | None:
    """Search Amazon for brand+title, extract the first ASIN, then scrape it."""
    query = f"{brand} {title}".strip()
    url = "https://www.amazon.com/s?k=" + query.replace(" ", "+")
    headers = {
        "User-Agent": _USER_AGENTS[hash(query) % len(_USER_AGENTS)],
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
    except Exception:
        return None

    _parser = "lxml"
    try:
        import lxml  # noqa: F401
    except ImportError:
        _parser = "html.parser"
    soup = BeautifulSoup(html, _parser)

    # Extract first search result ASIN from data-asin attribute
    asin = None
    for el in soup.select("[data-asin]"):
        val = el.get("data-asin", "")
        if val and re.fullmatch(r"[A-Z0-9]{10}", val):
            asin = val
            break

    if not asin:
        return None

    # Scrape the product page for the real title, bullets, category, image
    product = await _scrape_amazon(asin)
    return product

# ── Public entry point ────────────────────────────────────────────────────────

async def fetch_product(raw_input: str, manual_brand: str | None = None,
                        manual_title: str | None = None) -> Product:
    # Brand+title provided: try to find the real Amazon listing first.
    # This gives us real bullets, category, image, and canonical title.
    # Fall back to a stub product if the search/scrape fails or is blocked.
    if manual_brand and manual_title:
        found = None
        if not _IS_CLOUD:
            # Local env: try Amazon search scrape (usually works)
            found = await _search_and_fetch(manual_brand, manual_title)
        if not found and bool(os.environ.get("RAINFOREST_API_KEY", "")):
            # Cloud with Rainforest: use their search endpoint
            found = await _try_rainforest_search(manual_brand, manual_title)
        if found:
            return found
        # Fallback: stub with the user-provided data
        try:
            asin = _extract_asin(raw_input)
        except ValueError:
            asin = raw_input or "manual"
        return Product(asin=asin, brand=manual_brand, title=manual_title,
                       category=_STUB_CATEGORY, bullets=[], image_url=None)

    try:
        asin = _extract_asin(raw_input)
    except ValueError:
        return Product(asin=raw_input, brand="MANUAL_ENTRY_REQUIRED",
                       title=raw_input, category=_STUB_CATEGORY,
                       bullets=[], image_url=None)

    # Rainforest first whenever the key is set (reliable on all environments).
    # On cloud without a Rainforest key, skip scraping entirely  -  Amazon blocks
    # cloud IP ranges almost immediately, so the 10-second timeout is dead time.
    # Return MANUAL_ENTRY_REQUIRED instantly; the frontend shows the entry form.
    has_rainforest = bool(os.environ.get("RAINFOREST_API_KEY", ""))
    if has_rainforest:
        product = await _try_rainforest(asin) or await _scrape_amazon(asin)
    elif _IS_CLOUD:
        product = None  # scrape always blocked on cloud IPs; skip straight to manual form
    else:
        scraped = await _scrape_amazon(asin)
        product = scraped if (scraped and scraped.brand != "Unknown Brand") else None
        product = product or scraped

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
    Thin wrapper kept for API compatibility.
    LLM ASIN guessing was removed  -  it hallucinated products.
    If scraping + Rainforest both fail, returns MANUAL_ENTRY_REQUIRED
    so the frontend can show the manual-entry form.
    """
    return await fetch_product(raw_input, manual_brand, manual_title)
