"""AI Visibility Grader -- FastAPI backend."""
from __future__ import annotations
import hashlib
import json
import os
import time as _time
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import DiagnoseRequest, DiagnoseResponse, Product, QuerySummary
from services.product_fetcher import (
    ProductFetchError,
    _extract_listing,
    fetch_product_with_llm_fallback as fetch_product,
)
from services.query_generator import generate_queries
from services.llm_runner import run_all_queries
from services.parser import parse_query_results
from services.scorer import compute_score
from services.recommender import generate_recommendations


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = [k for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
                               "CANOPY_API_KEY", "KEEPA_API_KEY", "RAINFOREST_API_KEY")
                  if os.environ.get(k)]
    missing = [k for k in ("GROQ_API_KEY",) if not os.environ.get(k)]
    print(f"[startup] providers configured: {configured or 'none'}")
    if missing:
        print(f"[WARNING] Missing required env vars: {', '.join(missing)}")
    yield


app = FastAPI(title="AI Visibility Grader", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Full diagnostic cache.
# Repeat runs on the same product return the same diagnostic with zero LLM calls.
# Set DIAG_CACHE_DIR to a persistent disk path in production to survive deploys.
# ---------------------------------------------------------------------------
_DIAG_CACHE: dict[str, tuple[DiagnoseResponse, float]] = {}
_DIAG_CACHE_VERSION = os.environ.get("DIAG_CACHE_VERSION", "v3")
_DIAG_CACHE_TTL = int(os.environ.get("DIAG_CACHE_TTL_SECONDS", str(30 * 24 * 3600)))
_DIAG_CACHE_DIR = Path(os.environ.get("DIAG_CACHE_DIR") or Path(__file__).with_name(".diag_cache"))


def _diag_cache_key(asin: str, marketplace: str, category: str | None = None) -> str:
    payload = {
        "version": _DIAG_CACHE_VERSION,
        "asin": asin.upper(),
        "marketplace": marketplace.upper(),
        "category": category or "",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _diag_cache_path(key: str) -> Path:
    return _DIAG_CACHE_DIR / f"{key}.json"


def _diag_cache_get(key: str) -> DiagnoseResponse | None:
    entry = _DIAG_CACHE.get(key)
    if entry and (_time.time() - entry[1]) < _DIAG_CACHE_TTL:
        return entry[0]
    path = _diag_cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created_at = float(data.get("created_at", 0))
        if (_time.time() - created_at) >= _DIAG_CACHE_TTL:
            return None
        response = DiagnoseResponse.model_validate(data["response"])
        _DIAG_CACHE[key] = (response, created_at)
        return response
    except Exception:
        return None
    return None


def _diag_cache_set(key: str, response: DiagnoseResponse) -> None:
    created_at = _time.time()
    _DIAG_CACHE[key] = (response, created_at)
    try:
        _DIAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _diag_cache_path(key)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "created_at": created_at,
            "version": _DIAG_CACHE_VERSION,
            "response": response.model_dump(mode="json"),
        }
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception as exc:
        print(f"[cache] failed to persist diagnostic cache: {exc}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/product", response_model=Product)
async def get_product(request: DiagnoseRequest):
    """Fetch and return just the product for the loading screen preview."""
    if not request.listing_input:
        raise HTTPException(status_code=422, detail="Provide an Amazon product URL or ASIN.")
    try:
        product = await fetch_product(request.listing_input)
    except ProductFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if request.category and product.category == "Health & Household":
        product = product.model_copy(update={"category": request.category})
    if product.brand == "MANUAL_ENTRY_REQUIRED":
        raise HTTPException(status_code=422, detail=f"Could not resolve '{request.listing_input}' to an Amazon listing.")
    return product


@app.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest):
    if not request.listing_input:
        raise HTTPException(
            status_code=422,
            detail="Provide an Amazon product URL or ASIN so the exact listing can be fetched.",
        )

    # Fast path: return cached diagnostic if available.
    try:
        _asin_key, _marketplace = _extract_listing(request.listing_input)
        _cache_key = _diag_cache_key(_asin_key, _marketplace, request.category)
        cached_diag = _diag_cache_get(_cache_key)
        if cached_diag:
            return cached_diag
    except Exception:
        _cache_key = None

    # 1. Product
    try:
        product = await fetch_product(
            request.listing_input,
        )
    except ProductFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if request.category and product.category == "Health & Household":
        product = product.model_copy(update={"category": request.category})

    if product.brand == "MANUAL_ENTRY_REQUIRED":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not resolve '{request.listing_input}' to an Amazon listing. "
                "Submit a canonical Amazon product URL or a valid 10-character ASIN."
            ),
        )

    # 2. Generate 6 buyer queries
    queries = await generate_queries(product)
    if not queries:
        raise HTTPException(status_code=500, detail="Query generation failed.")

    # 3. Fan out to all 3 LLMs
    query_results = await run_all_queries(queries)

    # 4. Parse mentions and competitors
    parsed_results = await parse_query_results(query_results, product.brand)

    # 5. Score
    score = compute_score(parsed_results, product.brand)

    # 6. Generate 3 recommendations
    recommendations = await generate_recommendations(product, parsed_results, score)

    summaries = []
    for pr in parsed_results:
        positions = [p for p in [pr.position.gpt4, pr.position.claude, pr.position.gemini]
                     if p is not None]
        summaries.append(QuerySummary(
            query=pr.query,
            mentions=pr.mentions,
            winners=pr.competitors_mentioned[:3],
            your_position=min(positions) if positions else None,
        ))

    response = DiagnoseResponse(
        product=product, score=score, queries=summaries,
        top_competitors=score.top_competitors, recommendations=recommendations,
    )
    if _cache_key:
        _diag_cache_set(_cache_key, response)
    return response
