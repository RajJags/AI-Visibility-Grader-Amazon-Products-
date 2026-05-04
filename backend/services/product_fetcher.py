"""
ProductFetcher  -  resolves an exact Amazon URL/ASIN to a Product.

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
_DEFAULT_MARKETPLACE = os.environ.get("AMAZON_MARKETPLACE", "IN").upper()
_IS_CLOUD = bool(os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT")
                 or os.environ.get("FLY_APP_NAME") or os.environ.get("DYNO"))

_HOST_TO_MARKETPLACE = {
    "amazon.com": "US",
    "amazon.in": "IN",
    "amazon.co.uk": "UK",
    "amazon.ca": "CA",
    "amazon.de": "DE",
    "amazon.fr": "FR",
    "amazon.it": "IT",
    "amazon.es": "ES",
    "amazon.com.au": "AU",
    "amazon.co.jp": "JP",
}

_MARKETPLACE_TO_HOST = {v: k for k, v in _HOST_TO_MARKETPLACE.items()}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class ProductFetchError(RuntimeError):
    """Raised when exact listing lookup cannot run because a provider is unavailable."""


def _provider_error(provider: str, status: int, detail: str = "") -> ProductFetchError:
    suffix = f": {detail}" if detail else "."
    return ProductFetchError(f"{provider} product lookup is unavailable (HTTP {status}){suffix}")


def _extract_asin(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"(?:/dp/|/gp/product/)([a-z0-9]{10})", raw, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if re.fullmatch(r"[a-z0-9]{10}", raw, flags=re.IGNORECASE):
        return raw.upper()
    raise ValueError(f"Could not parse ASIN from: {raw!r}")


def _extract_marketplace(raw: str) -> str:
    host_match = re.search(r"https?://(?:www\.)?([^/]+)", raw.strip(), flags=re.IGNORECASE)
    if not host_match:
        return _DEFAULT_MARKETPLACE
    host = host_match.group(1).lower()
    return _HOST_TO_MARKETPLACE.get(host, _DEFAULT_MARKETPLACE)


def _extract_listing(raw: str) -> tuple[str, str]:
    return _extract_asin(raw), _extract_marketplace(raw)


def _amazon_domain(marketplace: str) -> str:
    return _MARKETPLACE_TO_HOST.get(marketplace.upper(), "amazon.in")


# Canopy

def _first_string(*values) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_image_url(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                url = _first_string(item.get("url"), item.get("link"), item.get("large"), item.get("hiRes"))
                if url:
                    return url
    if isinstance(value, dict):
        return _first_string(value.get("url"), value.get("link"), value.get("large"), value.get("hiRes")) or None
    return None


def _canopy_bullets(product: dict) -> list[str]:
    for key in ("features", "featureBullets", "feature_bullets", "bullets"):
        value = product.get(key)
        if isinstance(value, list):
            return [str(item) for item in value[:10] if str(item).strip()]
    description = product.get("description")
    if isinstance(description, list):
        return [str(item) for item in description[:10] if str(item).strip()]
    if isinstance(description, str) and description.strip():
        return [description.strip()]
    return []


def _canopy_category(product: dict) -> str:
    category = product.get("category") or product.get("productCategory") or product.get("productGroup")
    if isinstance(category, str) and category.strip():
        return category.strip()
    breadcrumbs = product.get("breadcrumbs") or product.get("categories")
    if isinstance(breadcrumbs, list):
        for item in breadcrumbs:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                name = _first_string(item.get("name"), item.get("title"))
                if name:
                    return name
    return _STUB_CATEGORY


def _fetch_canopy_sync(asin: str, marketplace: str) -> dict:
    api_key = os.environ.get("CANOPY_API_KEY", "")
    if not api_key:
        raise RuntimeError("CANOPY_API_KEY not set")
    params = {"asin": asin, "domain": marketplace.upper()}
    headers = {"API-KEY": api_key, "Accept": "application/json"}
    with httpx.Client(timeout=25) as client:
        resp = client.get("https://rest.canopyapi.co/api/amazon/product", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _try_canopy(asin: str, marketplace: str) -> Product | None:
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_canopy_sync, asin, marketplace)
        product = (
            data.get("product")
            if isinstance(data.get("product"), dict)
            else (data.get("data") or {}).get("amazonProduct")
            if isinstance(data.get("data"), dict)
            else data
        )
        if not isinstance(product, dict):
            return None
        title = _first_string(product.get("title"), product.get("productTitle"), product.get("name"))
        if not title:
            return None
        image_url = _first_image_url(
            product.get("imageUrl") or product.get("mainImage") or product.get("images") or product.get("image")
        )
        return Product(
            asin=_first_string(product.get("asin"), data.get("asin")) or asin,
            brand=_first_string(product.get("brand"), product.get("manufacturer")) or "Unknown Brand",
            title=title,
            category=_canopy_category(product),
            bullets=_canopy_bullets(product),
            image_url=image_url,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (400, 401, 402, 403, 429):
            detail = ""
            try:
                body = exc.response.json()
                detail = str(body.get("message") or body.get("error") or body.get("detail") or "")[:240]
            except Exception:
                pass
            raise _provider_error("Canopy", status, detail) from exc
        return None
    except Exception:
        return None


# Keepa

def _keepa_image_url(images_csv: str | None) -> str | None:
    if not images_csv:
        return None
    first = images_csv.split(",")[0].strip()
    if not first:
        return None
    return f"https://m.media-amazon.com/images/I/{first}"


def _keepa_category(product: dict) -> str:
    category_tree = product.get("categoryTree") or []
    if category_tree and isinstance(category_tree[0], dict):
        return category_tree[0].get("name") or _STUB_CATEGORY
    return product.get("productGroup") or _STUB_CATEGORY


def _fetch_keepa_sync(asin: str) -> dict:
    api_key = os.environ.get("KEEPA_API_KEY", "")
    if not api_key:
        raise RuntimeError("KEEPA_API_KEY not set")
    params = {
        "key": api_key,
        "domain": 1,
        "asin": asin,
        "history": 0,
        "stats": 0,
    }
    with httpx.Client(timeout=20) as client:
        resp = client.get("https://api.keepa.com/product", params=params)
        resp.raise_for_status()
        return resp.json()


async def _try_keepa(asin: str) -> Product | None:
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_keepa_sync, asin)
        products = data.get("products") or []
        if not products:
            return None
        prod = products[0]
        title = prod.get("title") or ""
        if not title:
            return None
        bullets = prod.get("features") or []
        return Product(
            asin=prod.get("asin") or asin,
            brand=prod.get("brand") or "Unknown Brand",
            title=title,
            category=_keepa_category(prod),
            bullets=[str(b) for b in bullets[:10]],
            image_url=_keepa_image_url(prod.get("imagesCSV")),
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 402, 403, 429):
            detail = ""
            try:
                body = exc.response.json()
                detail = str(body.get("error") or body.get("message") or "")[:240]
            except Exception:
                pass
            raise _provider_error("Keepa", status, detail) from exc
        return None
    except Exception:
        return None


# ── Rainforest ────────────────────────────────────────────────────────────────

def _fetch_rainforest_sync(asin: str, marketplace: str) -> dict:
    api_key = os.environ.get("RAINFOREST_API_KEY", "")
    if not api_key:
        raise RuntimeError("RAINFOREST_API_KEY not set")
    params = {"api_key": api_key, "type": "product", "asin": asin,
              "amazon_domain": _amazon_domain(marketplace)}
    with httpx.Client(timeout=15) as client:
        resp = client.get("https://api.rainforestapi.com/request", params=params)
        resp.raise_for_status()
        return resp.json()


async def _try_rainforest(asin: str, marketplace: str) -> Product | None:
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_rainforest_sync, asin, marketplace)
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
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 402, 403, 429):
            raise ProductFetchError(
                f"Amazon listing lookup provider is unavailable (Rainforest API returned HTTP {status}). "
                "Check the Rainforest account/API key, then retry with the same ASIN or Amazon URL."
            ) from exc
        return None
    except Exception:
        return None


# ── Amazon scrape ─────────────────────────────────────────────────────────────

async def _scrape_amazon(asin: str, marketplace: str) -> Product | None:
    url = f"https://www.{_amazon_domain(marketplace)}/dp/{asin}"
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




# ── Public entry point ────────────────────────────────────────────────────────

async def fetch_product(raw_input: str, manual_brand: str | None = None,
                        manual_title: str | None = None) -> Product:
    # Exact listing mode only: raw_input must be a canonical product URL or ASIN.
    # Brand/title search is intentionally disabled because it can select bundles,
    # protection plans, accessories, or the wrong variant.
    try:
        asin, marketplace = _extract_listing(raw_input)
    except ValueError:
        return Product(asin=raw_input, brand="MANUAL_ENTRY_REQUIRED",
                       title=raw_input, category=_STUB_CATEGORY,
                       bullets=[], image_url=None)

    # Rainforest first whenever the key is set (reliable on all environments).
    # On cloud without a Rainforest key, skip scraping entirely  -  Amazon blocks
    # cloud IP ranges almost immediately, so the 10-second timeout is dead time.
    # Return MANUAL_ENTRY_REQUIRED instantly; the frontend shows the entry form.
    provider_errors: list[str] = []
    product = None

    if os.environ.get("CANOPY_API_KEY", ""):
        try:
            product = await _try_canopy(asin, marketplace)
        except ProductFetchError as exc:
            provider_errors.append(str(exc))

    if not product and os.environ.get("KEEPA_API_KEY", ""):
        try:
            product = await _try_keepa(asin)
        except ProductFetchError as exc:
            provider_errors.append(str(exc))

    has_rainforest = bool(os.environ.get("RAINFOREST_API_KEY", ""))
    if not product and has_rainforest:
        try:
            product = await _try_rainforest(asin, marketplace)
        except ProductFetchError as exc:
            provider_errors.append(str(exc))
            product = None
        product = product or await _scrape_amazon(asin, marketplace)
    elif not product and _IS_CLOUD:
        product = None  # scrape always blocked on cloud IPs; skip straight to manual form
    elif not product:
        scraped = await _scrape_amazon(asin, marketplace)
        product = scraped if (scraped and scraped.brand != "Unknown Brand") else None
        product = product or scraped

    if product:
        return product

    if provider_errors:
        raise ProductFetchError(" ".join(provider_errors))

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
    LLM ASIN guessing and brand/title search are intentionally disabled:
    exact listing fetches require a URL or ASIN.
    """
    return await fetch_product(raw_input, manual_brand, manual_title)
