# AI Visibility Grader (Amazon)

How visible is your Amazon product to AI shopping assistants, and what should you improve in the listing?

AI Visibility Grader resolves an exact Amazon listing, generates realistic buyer queries, asks multiple LLM shopping assistants for recommendations, and scores whether the target product appears. It then turns the gaps into concrete Amazon listing improvements.

## What It Does

Given an exact Amazon product URL or ASIN, the system:

1. Resolves the listing and marketplace.
2. Fetches product metadata, feature bullets, image, category, and structured specs.
3. Generates 6 non-branded buyer-intent queries using the listing specs where available.
4. Runs those queries across Llama 3.3 70B, Llama 3.1 8B, and Gemini.
5. Parses brand mentions, rank positions, competitor brands, and praised attributes.
6. Computes a 0-100 visibility score.
7. Recommends 3 listing improvements grounded in competitor gaps and weak query types.

## Live Demo

https://aivisibilitygrader.vercel.app

First request may take 10-15 seconds because the backend can cold start.

## Why URL or ASIN Is Required

Early versions tried to resolve products from brand and title search. That made the pipeline vulnerable to picking a bundle, accessory, warranty, wrong marketplace item, or wrong variant.

This project now requires deterministic identifiers:

- Full Amazon product URL, such as `https://amazon.in/dp/B0XXXX`
- Raw ASIN, such as `B0XXXX`

If the product identity is wrong, every downstream AI visibility result becomes misleading.

## Architecture

Frontend: Next.js

Backend: FastAPI

Pipeline:

1. Product Fetcher
   - Extracts ASIN and marketplace from URL or raw ASIN.
   - Fetches listing data via provider chain.
   - Extracts structured specs from API fields or Amazon detail tables.
   - Exposes a lightweight `/product` preview endpoint so the loading screen can show the fetched product title, brand, and image before the full diagnostic finishes.

2. Query Generator
   - Uses product title, category, bullets, and structured specs.
   - Generates spec-aware, non-branded buyer queries.
   - Cleans awkward grammar, normalizes units, and preserves currency context in price queries.
   - Returns exactly 6 clean queries.

3. LLM Runner
   - Sends each query to Llama 3.3 70B, Llama 3.1 8B, and Gemini.
   - Runs model calls in parallel where possible.

4. Parser
   - Parses all three model responses for each query in a compact batched LLM call.
   - Extracts target mentions, rank positions, competitors, and brand attributes.

5. Scorer
   - Computes overall and per-model visibility scores.
   - Tracks top competitors and the number of scored queries.
   - Reuses a full diagnostic cache so repeat runs for the same product return the same score.

6. Recommender
   - Compares current listing language and specs against competitor attributes.
   - Weighs gaps from lost and won queries.
   - Produces 3 data-backed Amazon listing recommendations.

## Product Data Layer

Reliable product lookup is critical, so the backend uses a provider chain:

1. Canopy API
2. Keepa
3. Rainforest API
4. Amazon page scraping for local/dev fallback

Structured specs are pulled from provider fields such as technical details, specifications, attributes, product details, or scraped Amazon product detail tables. These specs help the query generator create realistic searches like `laptop with 16GB RAM for office work` instead of generic category prompts.

## Query Quality

Generated queries are treated as buyer-search phrases, but the backend still normalizes them before scoring and display. Cleanup includes:

- Removing awkward phrases such as `under budget 20` and `good for`.
- Normalizing duration phrasing such as `7 hours playtime` to `7-hour playtime`.
- Keeping price searches specific by adding or preserving currency, such as `under 20 dollars`, `under INR 1500`, or `under $20`.
- Padding short LLM outputs with category-aware fallback queries instead of generic electronics-only language.

## Marketplace Handling

ASIN availability can differ by marketplace.

Rules:

- URL input: marketplace is inferred from the Amazon domain, such as `amazon.in` or `amazon.com`.
- Raw ASIN input: marketplace defaults to `AMAZON_MARKETPLACE`, currently `IN` unless changed.

## Cost and Latency

This is a multi-step LLM pipeline.

Typical run:

- 6 generated buyer queries
- 18 shopping-assistant model calls
- 6 batched parser calls
- 1 recommendation call

Latency depends on provider speed, free-tier limits, and backend cold starts.

## Result Consistency

LLM calls are configured with zero temperature, and full diagnostic responses are cached by ASIN, marketplace, optional category override, and cache version. Repeat runs return the cached diagnostic so the same product does not bounce between different visibility scores.

For deployed environments, set `DIAG_CACHE_DIR` to a persistent disk path. Without persistent storage, the in-memory and local file cache still stabilizes repeat runs within the current backend instance, but a fresh deploy may start with an empty cache.

To intentionally invalidate cached diagnostics after a scoring or prompt change, update `DIAG_CACHE_VERSION`.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Groq API key
- Google AI Studio API key
- Optional product-data provider keys: Canopy, Keepa, Rainforest

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

On Windows:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000.

## Environment Variables

### `backend/.env`

```env
GROQ_API_KEY=
GOOGLE_API_KEY=
OPENROUTER_API_KEY=
CANOPY_API_KEY=
KEEPA_API_KEY=
RAINFOREST_API_KEY=
AMAZON_MARKETPLACE=IN
FRONTEND_URL=http://localhost:3000
DIAG_CACHE_DIR=
DIAG_CACHE_VERSION=v3
DIAG_CACHE_TTL_SECONDS=2592000
```

### `frontend/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## API

### `POST /product`

Fetches only the resolved Amazon product. The frontend uses this first to show the real product and brand on the loading screen while the full diagnostic runs.

Request:

```json
{
  "asin": "B0XXXX"
}
```

Simplified response:

```json
{
  "asin": "B0XXXX",
  "brand": "Brand",
  "title": "Product title",
  "category": "Category",
  "bullets": ["Feature bullet"],
  "image_url": "https://...",
  "specs": {
    "Battery Life": "7 Hours"
  }
}
```

### `POST /diagnose`

Request with URL:

```json
{
  "amazon_url": "https://amazon.in/dp/B0XXXX"
}
```

Request with ASIN:

```json
{
  "asin": "B0XXXX"
}
```

Simplified response:

```json
{
  "product": {
    "asin": "B0XXXX",
    "brand": "Brand",
    "title": "Product title",
    "category": "Category",
    "bullets": ["Feature bullet"],
    "image_url": "https://...",
    "specs": {
      "RAM": "16 GB",
      "Battery Life": "18 Hours"
    }
  },
  "score": {
    "overall": 62,
    "gpt4": 70,
    "claude": 55,
    "gemini": 61,
    "top_competitors": [],
    "queries_used": 6
  },
  "queries": [],
  "top_competitors": [],
  "recommendations": []
}
```

## Deployment

### Backend on Render

- Root directory: `backend/`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Add backend environment variables in Render.

### Frontend on Vercel

- Root directory: `frontend/`
- Add `NEXT_PUBLIC_API_URL`
- Deploy normally from the frontend project.

## Troubleshooting

### Product Not Found

- Check marketplace mismatch, especially `IN` vs `US`.
- Try a full Amazon product URL instead of a raw ASIN.
- Ensure at least one product-data provider key is configured for production.

### Provider API Failures

- Check API quota, billing, and key validity.
- 401, 402, 403, and 429 responses usually indicate auth, billing, permission, or rate-limit issues.

### Amazon Scraping Issues

- Amazon often blocks cloud IPs.
- Use Canopy, Keepa, or Rainforest for production lookup reliability.

### Slow Diagnostics

- Expected for a multi-model LLM workflow.
- Free-tier model latency and backend cold starts can dominate runtime.

### LLM Rate Limits

- Groq or Gemini may throttle requests.
- Retry after the limit resets or configure fallback providers where supported.

## Engineering Notes

- Exact product identity matters more than fuzzy convenience.
- Structured product specs make buyer queries more realistic.
- Parser calls are batched to reduce LLM-to-LLM overhead.
- Recommendations are grounded in observed model responses, competitor attributes, and current listing text.

## License

MIT
