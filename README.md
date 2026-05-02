# AI Visibility Grader

**Is your Amazon product invisible to AI shoppers?**

AI Visibility Grader tells Amazon sellers how often ChatGPT, Claude, and Gemini recommend their brand when shoppers ask realistic buying questions. Paste an ASIN, get a 0–100 score, see exactly which queries you're losing to competitors, and receive 5 specific listing improvements — in about 60 seconds.

Built as a companion to [Pixii](https://pixii.ai). Pixii grades listings for human clickability. This grades them for **AI recommendability**.

---

## Why this matters

Research suggests that 20–30% of online shoppers now ask an AI assistant before visiting Amazon. If your brand doesn't appear in those responses, you're invisible before the shopping journey begins. Traditional listing optimisation (keywords, images, reviews) doesn't automatically translate into AI recommendation signals. This tool makes the gap measurable.

---

## What you get

- **AI Visibility Score (0–100)** — a single number summarising how often all three major AI models recommend your brand
- **Per-model breakdown** — separate scores for GPT-4o, Claude, and Gemini
- **Query-level table** — 10 realistic buyer queries, showing which models mentioned you and what position
- **Top competitors** — the 5 brands that beat you most frequently, ranked by mention count
- **5 specific recommendations** — grounded in the exact queries you lost and the attributes your competitors have that you don't

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (Next.js 14, Vercel)                           │
│  POST /diagnose { asin }   →   DiagnoseResponse JSON    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Backend (FastAPI, Render)                               │
│                                                         │
│  1. ProductFetcher   ASIN → Product (Rainforest API)    │
│  2. QueryGenerator   Product → 10 buyer queries (GPT-4o)│
│  3. LLMRunner        10 queries × 3 models = 30 calls   │
│                      (asyncio.gather, parallel)          │
│  4. ResponseParser   30 responses → structured JSON     │
│                      (GPT-4o as structured extractor)   │
│  5. Scorer           Weighted position scoring → 0–100  │
│  6. Recommender      Diagnostic data → 5 fixes (GPT-4o) │
└─────────────────────────────────────────────────────────┘
```

Each module is a single file with a single responsibility and is independently swappable.

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys for: OpenAI, Anthropic, Google Gemini
- (Optional) Rainforest API key for live ASIN lookups

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # fill in your API keys
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
| `OPENAI_API_KEY` | Yes | GPT-4o for queries, parsing, recommendations |
| `ANTHROPIC_API_KEY` | Yes | Claude for LLM scoring |
| `GOOGLE_API_KEY` | Yes | Gemini for LLM scoring |
| `RAINFOREST_API_KEY` | No | Live ASIN lookups. Without it, fetch returns a stub. |
| `FRONTEND_URL` | No | CORS origin (default: `http://localhost:3000`) |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | No | Backend URL (default: `http://localhost:8000`) |

---

## Deployment

### Backend → Render (free tier)

1. Push the repo to GitHub
2. Create a new **Web Service** on Render, pointing to the `backend/` folder
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add all environment variables in the Render dashboard

### Frontend → Vercel

1. Import the repo into Vercel
2. Set the **Root Directory** to `frontend/`
3. Add `NEXT_PUBLIC_API_URL` pointing to your Render backend URL
4. Deploy

---

## Scoring algorithm

```
Per model score:
  sum(position_weight(mention_position)) / total_queries × 100

Position weights:
  1st mention → 1.0
  2nd mention → 0.7
  3rd mention → 0.5
  4th+        → 0.3
  Not mentioned → 0.0

Overall score:
  average(gpt4_score, claude_score, gemini_score)
```

---

## Repo structure

```
ai-visibility-grader/
├── backend/
│   ├── main.py                 # FastAPI app, /diagnose endpoint
│   ├── models.py               # Pydantic schemas
│   ├── services/
│   │   ├── product_fetcher.py  # ASIN → Product
│   │   ├── query_generator.py  # Product → 10 buyer queries
│   │   ├── llm_runner.py       # 30 parallel LLM calls
│   │   ├── parser.py           # Extract mentions & competitors
│   │   ├── scorer.py           # Weighted position scoring
│   │   └── recommender.py      # 5 GPT-4o recommendations
│   ├── llm_clients/
│   │   ├── base.py
│   │   ├── openai_client.py
│   │   ├── anthropic_client.py
│   │   └── gemini_client.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   └── page.tsx            # Landing + inline report
│   ├── components/
│   │   ├── ScoreHero.tsx
│   │   ├── ModelCard.tsx
│   │   ├── QueryTable.tsx
│   │   ├── CompetitorList.tsx
│   │   ├── RecommendationCard.tsx
│   │   └── LoadingScreen.tsx
│   ├── lib/api.ts              # Backend API client
│   ├── package.json
│   └── .env.local.example
├── README.md
└── .gitignore
```

---

## What I'd build next

**Short-term (next sprint)**
- SSE progress stream (`GET /diagnose/stream/{job_id}`) so the loading screen reflects real pipeline state
- Save/share reports via a unique URL — add Postgres and a `diagnostics` table
- PDF export of the report

**Medium-term**
- User auth (Clerk or Supabase) + report history dashboard
- Comparison mode: paste two ASINs and see them scored side-by-side
- Webhook/scheduled re-runs (Celery + Redis) to track score over time

**Scale / cost optimisation**
- Replace per-request GPT-4o parser calls with a fine-tuned `claude-haiku` or regex + spaCy NER pipeline — would cut parsing cost ~10×
- Cache `(product_category, query)` → LLM response in Redis; repeat calls for the same category hit the cache, reducing live API calls by ~80%
- Move to a job queue (Celery + Redis) when load grows — the stateless backend already supports this
- Add Postgres with `diagnostics`, `queries`, `responses` tables, partitioned by `created_at`

**Product**
- Multi-language support (Spanish, German) — already handled if we swap the query generator prompt
- Slack/email delivery of weekly score changes
- Agency multi-seat tier with white-labelling
"# AI-Visibility-Grader-Amazon-Products-" 
