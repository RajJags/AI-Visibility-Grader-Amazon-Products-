# AI Visibility Grader (Amazon)

**How visible is your product to AI shopping assistants — and how do you improve it?**

This project analyzes an Amazon product and estimates how often it appears in AI-generated recommendations (LLMs like Llama/Gemini), then suggests concrete listing improvements.

---

## What this does

Given an **exact Amazon product URL or ASIN**, the system:

1. Fetches the real product listing (title, features, category, etc.)
2. Generates realistic buyer-intent queries (non-branded)
3. Asks multiple LLMs what products they would recommend
4. Checks whether your product/brand appears
5. Scores visibility (0–100)
6. Identifies competitors winning those queries
7. Generates actionable listing improvements

---

## Why exact URL / ASIN is required

Early versions used:

brand + product title → Amazon search → closest match

This introduced non-deterministic entity resolution.

“Closest match” could be:
- the bundle, not the product  
- the warranty, not the item  
- or the wrong variant altogether  

The pipeline didn’t fail —  
it ran correctly on the wrong entity.

Fix:
→ enforce **deterministic identifiers (ASIN / URL)**

> If product identity is wrong, everything downstream becomes meaningless.

---

## Live Demo

https://aivisibilitygrader.vercel.app

(First request may take ~10–15s due to backend cold start)

---

## Architecture Overview

Frontend (Next.js)  
→ submits ASIN / URL  

Backend (FastAPI)

1. Product Fetcher  
   → resolve ASIN + marketplace  
   → fetch product data via provider chain  

2. Query Generator (LLM)  
   → generate 10 generic buyer queries  

3. LLM Runner  
   → ask multiple models (parallel)  
   → collect recommendations  

4. Parser (LLM)  
   → structure responses into ranked product lists  

5. Scorer  
   → compute visibility score (position-weighted)  

6. Recommender (LLM)  
   → generate listing improvements  

---

## Product Data Layer

Reliable product lookup is critical.

Provider chain:

1. Canopy API (primary)  
2. Keepa (fallback)  
3. Rainforest API (fallback)  
4. Amazon scraping (last resort / dev fallback)  

---

## Marketplace Handling

- ASINs are **marketplace-specific**
- Same ASIN may exist in India but not in the US

Rules:
- If input = URL → infer marketplace from domain (amazon.in, amazon.com)
- If input = raw ASIN → use AMAZON_MARKETPLACE (default: IN)

---

## Cost & Latency

This is a multi-step LLM pipeline.

Typical run:
- ~40+ LLM calls  
- Multiple providers  
- Parallel execution  

Latency:
~60–100 seconds (free tier)

Tradeoff:
quality vs cost vs latency

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+

Accounts (free tiers):
- Groq
- Google AI Studio (Gemini)
- (Optional) Canopy / Keepa / Rainforest

---

## Backend

cd backend

python -m venv .venv  
source .venv/bin/activate   (Windows: .venv\Scripts\activate)

pip install -r requirements.txt  
cp .env.example .env  

uvicorn main:app --reload --port 8000  

---

## Frontend

cd frontend  

npm install  
cp .env.local.example .env.local  

npm run dev  

Open http://localhost:3000

---

## Environment Variables

### backend/.env

GROQ_API_KEY=  
GOOGLE_API_KEY=  
CANOPY_API_KEY=  
KEEPA_API_KEY=  
RAINFOREST_API_KEY=  
AMAZON_MARKETPLACE=IN  

---

### frontend/.env.local

NEXT_PUBLIC_API_URL=http://localhost:8000

---

## API

POST /diagnose

Request:
{
  "input": "https://amazon.in/dp/B0XXXX"
}

or

{
  "input": "B0XXXX"
}

---

Response (simplified):

{
  "score": 62,
  "model_scores": {
    "llama70b": 70,
    "llama8b": 55,
    "gemini": 61
  },
  "competitors": ["BrandA", "BrandB"],
  "recommendations": [
    "Improve feature clarity",
    "Add comparison-friendly attributes"
  ]
}

---

## Deployment

### Backend (Render)

- Root: backend/
- Build: pip install -r requirements.txt
- Start: uvicorn main:app --host 0.0.0.0 --port $PORT
- Add env variables

---

### Frontend (Vercel)

- Root: frontend/
- Add NEXT_PUBLIC_API_URL
- Deploy

---

## Troubleshooting

### Product not found
- Check marketplace mismatch (IN vs US)
- Try full URL instead of ASIN
- Ensure provider API keys are set

---

### Provider API failures
- Check quotas / billing
- Verify API keys
- Look for 402 / auth errors

---

### Scraping issues
- Amazon blocks cloud IPs
- Scraping is not reliable in production
→ Use provider APIs

---

### Slow diagnostics
- Expected due to multiple LLM calls
- Free-tier latency adds up

---

### LLM rate limits
- Providers may throttle
- Retry or add fallback providers

---

## Engineering Notes

- Exact product identity > fuzzy UX
- AI systems fail silently with bad input
- Surface provider errors, don’t hide them
- Latency is a core product constraint

---

## License

MIT
