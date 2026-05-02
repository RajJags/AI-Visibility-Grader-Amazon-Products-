"""AI Visibility Grader -- FastAPI backend. Single endpoint: POST /diagnose"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import DiagnoseRequest, DiagnoseResponse, QuerySummary
from services.product_fetcher import fetch_product_with_llm_fallback as fetch_product
from services.query_generator import generate_queries
from services.llm_runner import run_all_queries
from services.parser import parse_query_results
from services.scorer import compute_score
from services.recommender import generate_recommendations


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = [k for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
                               "RAINFOREST_API_KEY") if os.environ.get(k)]
    missing = [k for k in ("GROQ_API_KEY",) if not os.environ.get(k)]
    print(f"[startup] providers configured: {configured or 'none'}")
    if missing:
        print(f"[WARNING] Missing required env vars: {', '.join(missing)}")
    yield


app = FastAPI(title="AI Visibility Grader", version="0.1.0", lifespan=lifespan)

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


@app.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest):
    # 1. Product
    product = await fetch_product(request.asin, manual_brand=request.brand,
                                  manual_title=request.title)
    if request.category and product.category == "Health & Household":
        product = product.model_copy(update={"category": request.category})

    if product.brand == "MANUAL_ENTRY_REQUIRED":
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not resolve '{request.asin}' to a product. "
                "Re-submit with 'brand' and 'title' fields to bypass product lookup."
            ),
        )

    # 2. Generate buyer queries
    queries = await generate_queries(product)
    if not queries:
        raise HTTPException(status_code=500, detail="Query generation failed.")

    # 3. Fan out to all 3 LLMs in parallel
    query_results = await run_all_queries(queries)

    # 4. Parse mentions and competitors (batched LLM -- 1 call per query)
    parsed_results = await parse_query_results(query_results, product.brand)

    # 5. Score
    score = compute_score(parsed_results)

    # 6. Recommendations
    recommendations = await generate_recommendations(product, parsed_results, score)

    # Build response
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

    return DiagnoseResponse(
        product=product, score=score, queries=summaries,
        top_competitors=score.top_competitors, recommendations=recommendations,
    )
