# AI Visibility Grader

**Is your Amazon product invisible to AI shoppers?**

AI Visibility Grader tells Amazon sellers how often Llama, Gemini, and other AI models recommend their brand when shoppers ask realistic buying questions. Paste an ASIN, get a 0-100 score, see exactly which queries you're losing to competitors, and receive 5 specific listing improvements -- in about 60 seconds.

> **Built as a companion to [Pixii](https://pixii.ai).** Pixii grades listings for human clickability. This grades them for **AI recommendability** -- the layer Pixii does not yet cover. If I were joining the Pixii team, this is the kind of complementary diagnostic I'd want us to offer sellers.

---

## Try it live

**[ai-visibility-grader.vercel.app](https://ai-visibility-grader.vercel.app)** -- paste any Amazon ASIN and get a full AI visibility report in ~60 seconds. No login required.

> First request may take 10-15 s while the Render backend wakes from sleep.

---

![AI Visibility Grader screenshot](docs/hero.png)

---

## Why this matters

Research suggests 20-30% of online shoppers now ask an AI assistant before visiting Amazon. If your brand doesn't appear in those responses, you're invisible before the shopping journey begins. Traditional listing optimisation (keywords, images, reviews) doesn't automatically translate into AI recommendation signals. This tool makes the gap measurable.

---

## What you get

- **AI Visibility Score (0-100)** -- a single number summarising how often all three major AI models recommend your brand
- **Per-model breakdown** -- separate scores for Llama 3.3 70B, Llama 3.1 8B, and Gemini
- **Query-level table** -- 10 realistic buyer queries, showing which models mentioned you and at what position
- **Top competitors** -- the 5 brands that beat you most frequently, ranked by mention count
- **5 specific recommendations** -- grounded in the exact queries you lost and the attributes your competitors have that you don't

---

## Architecture

```
+----------------------------------------------------------+
|  Frontend (Next.js 14, Vercel)                           |
|  POST /diagnose { asin }  ->  DiagnoseResponse JSON      |
+-------------------------+--------------------------------+
                          |
+-------------------------v--------------------------------+
|  Backend (FastAPI, Render)                               |
|                                                          |
|  1. ProductFetcher    ASIN -> Product (Rainforest API)   |
|  2. QueryGenerator   Product -> 10 buyer queries (Groq)  |
|  3. LLMRunner        10 queries x 3 models = 30 calls    |
|                      (asyncio.gather, fully parallel)     |
|  4. ResponseParser   30 responses -> structured JSON      |
|                      (batched: 10 LLM calls, not 30)     |
|  5. Scorer           Weighted position scoring -> 0-100   |
|  6. Recommender      Diagnostic data -> 5 fixes (Groq)   |
+----------------------------------------------------------+
```

Each module is a single file with a single responsibility and is independently swappable.

---

## Engineering decisions

**Why Groq + OpenRouter instead of OpenAI?**
Groq serves Llama 3.3 70B with sub-second token generation on free-tier credits, making the demo accessible without a paid API key. OpenRouter acts as an automatic fallback when Groq is rate-limited. A circuit breaker (`llm_clients/_health.py`) tracks per-model failure timestamps and routes around degraded providers for 35 seconds, so a single rate-limit event doesn't cascade into a failed request.

**Why batch the parser to 10 calls instead of 30?**
The original design made one LLM call per model response (30 total). Batching all three model responses into a single parsing call per query cuts the parsing phase from ~30 LLM calls to 10, saving roughly 20-25 seconds of wall-clock time with no accuracy loss (the LLM sees the same data, just concatenated).

**Why asyncio.gather for the 30 LLM calls?**
All 30 query-by-model combinations are independent. Running them with `asyncio.gather` means the entire scoring run is bounded by the slowest single call (~8-10 s) rather than the sum (~5 min sequential). A semaphore (`asyncio.Semaphore(4)`) on the GenerationClient prevents TPM-limit bursts during the parallel parse phase.

**Why Rainforest API first on cloud, Amazon scrape locally?**
Amazon blocks requests from cloud IP ranges (Render, Railway, Fly) almost immediately. Rainforest proxies through residential IPs reliably. Locally the scrape usually works, so the code tries scraping first on non-cloud environments to save Rainforest API credits.

**Why position-weighted scoring instead of binary mention/no-mention?**
Ranking 1st in an AI response is meaningfully better than ranking 5th. The weights (1st=1.0, 2nd=0.7, 3rd=0.5, 4th+=0.3, mentioned-without-rank=0.25) capture this without over-penalising prose responses where position is ambiguous.

---

## Cost and latency

All providers used are **free tier**.

| Phase | Provider | Calls per run | Typical latency |
|---|---|---|---|
| Query generation | Groq (Llama 3.3 70B) | 1 | ~2 s |
| LLM scoring | Groq + Gemini | 30 parallel | ~8-10 s |
| Response parsing | Groq (Llama 3.3 70B) | 10 parallel | ~12-15 s |
| Recommendations | Groq (Llama 3.3 70B) | 1 | ~3 s |
| **Total** | | **42 LLM calls** | **~30-60 s** |

End-to-end cost per run is effectively $0 on free tiers. With paid APIs (e.g. GPT-4o for all steps), estimated cost would be ~$0.03-0.05 per run at current pricing.

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys for: Groq (free), Google Gemini (free)
- Optional: OpenRouter (free fallback), Rainforest API (reliable ASIN lookups)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # fill in GROQ_API_KEY and GOOGLE_API_KEY
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL if needed
npm run dev
```

Open `http://localhost:3000`.

---

## Environment variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Llama 3.3 70B and 3.1 8B -- query gen, parsing, recommendations |
| `GOOGLE_API_KEY` | Yes | Gemini 1.5 Flash -- LLM scoring |
| `OPENROUTER_API_KEY` | No | Fallback when Groq is rate-limited |
| `RAINFOREST_API_KEY` | No | Reliable ASIN lookups on cloud. Without it, the backend scrapes Amazon (works locally, often blocked on Render). |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | No | Backend URL (default: `http://localhost:8000`) |

---

## Deployment

### Backend -> Render (free tier)

1. Push the repo to GitHub
2. Create a new **Web Service** on Render, pointing to the `backend/` folder
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables in the Render dashboard

### Frontend -> Vercel

1. Import the repo into Vercel
2. Set the **Root Directory** to `frontend/`
3. Add `NEXT_PUBLIC_API_URL` pointing to your Render backend URL
4. Deploy

---

## Scoring algorithm

```
Per model score:
  sum(position_weight(mention_position)) / total_queries x 100

Position weights:
  1st mention -> 1.0
  2nd mention -> 0.7
  3rd mention -> 0.5
  4th+ mention -> 0.3
  Mentioned (no rank detected) -> 0.25
  Not mentioned -> 0.0

Overall score:
  average(llama70b_score, llama8b_score, gemini_score)
```

The 0.25 weight for "mentioned without rank" handles prose responses where the model recommends a brand in a paragraph rather than a numbered list.

---

## Repo structure

```
ai-visibility-grader/
+-- backend/
|   +-- main.py                  # FastAPI app, /diagnose endpoint
|   +-- models.py                # Pydantic schemas (Product, Score, etc.)
|   +-- services/
|   |   +-- product_fetcher.py   # ASIN -> Product (Rainforest + scrape)
|   |   +-- query_generator.py   # Product -> 10 buyer queries
|   |   +-- llm_runner.py        # 30 parallel LLM calls
|   |   +-- parser.py            # Batched LLM extraction (10 calls)
|   |   +-- scorer.py            # Weighted position scoring
|   |   +-- recommender.py       # 5 improvement recommendations
|   +-- llm_clients/
|   |   +-- _health.py           # Circuit breaker (35s cooldown per model)
|   |   +-- base.py              # Abstract client interface
|   |   +-- groq_client.py       # Llama 3.3 70B + 3.1 8B via Groq
|   |   +-- openrouter_client.py # Fallback via OpenRouter
|   |   +-- gemini_client.py     # Gemini 1.5 Flash
|   |   +-- generation_client.py # Health-aware provider router
|   +-- requirements.txt
|   +-- .env.example
+-- frontend/
|   +-- app/
|   |   +-- layout.tsx
|   |   +-- globals.css
|   |   +-- page.tsx             # Landing + inline report
|   +-- components/
|   |   +-- ScoreHero.tsx
|   |   +-- ModelCard.tsx
|   |   +-- QueryTable.tsx
|   |   +-- CompetitorList.tsx
|   |   +-- RecommendationCard.tsx
|   |   +-- LoadingScreen.tsx
|   +-- lib/api.ts               # Backend API client
|   +-- package.json
|   +-- .env.local.example
+-- docs/
|   +-- hero.png
+-- LICENSE
+-- README.md
```

---

## Roadmap

- **SSE progress stream** -- `GET /diagnose/stream/{job_id}` so the loading screen reflects real pipeline state instead of estimated timings
- **Persistent reports** -- save results to Postgres with a shareable URL; add a `diagnostics` table partitioned by `created_at`
- **Scheduled re-runs** -- weekly Celery job that re-scores a seller's ASIN and emails the delta, tracking visibility over time
- **Comparison mode** -- paste two ASINs and see them scored side-by-side, with diff highlighting on the query table
- **Pixii integration** -- pass the AI Visibility score and top competitor attributes back into Pixii's listing grader so sellers see both human and AI recommendability in one dashboard
- **Multi-language** -- swap the query generator prompt for Spanish, German, French; the rest of the pipeline is language-agnostic

---

## License

MIT. See [LICENSE](LICENSE).
