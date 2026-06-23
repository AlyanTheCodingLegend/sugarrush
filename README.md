# Sugar Rush Scout Agent

An on-demand competitive intelligence agent for **Sugar Rush Islamabad** (a dessert / ice cream shop in Kohsar Market, F-6). Send a WhatsApp command and the agent fetches live public data about Islamabad dessert competitors, cleans and stores it, runs an AI analysis pass, and replies with a concrete business report — all in under 60 seconds.

> **This is a real working prototype.** No mock data, no hand-prepared CSVs. Every competitor finding is fetched programmatically at runtime.

---

## Available Commands

| Command | What it does |
|---|---|
| `scout` | Full competitive intelligence report (always live fetch) |
| `alerts` | Highest-impact recent competitor moves only |
| `competitors` | What each competitor is currently doing online |
| `campaigns` | Current promotions, seasonal campaigns, content trends |
| `opportunities` | Gaps Sugar Rush can exploit + concrete moves |
| `pricing` | Competitor pricing / menu signals (where publicly available) |
| `content` | Top-performing content types + Sugar Rush content ideas |
| `help` | List all commands |

---

## How to Run

### Prerequisites

- Python 3.11+
- [ngrok](https://ngrok.com/download) — to expose the local server to Meta's webhook
- API keys for: Firecrawl, Apify, Google Places, Groq, Meta WhatsApp Cloud API

### Local setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env and fill in all API keys (see .env.example for instructions)

# 4. Start the API server
uvicorn app.main:app --port 8000

# 5. In a second terminal, start ngrok (use your permanent domain if you have one)
ngrok http 8000
# Copy the https://....ngrok-free.app URL
```

### Configure Meta WhatsApp Cloud API webhook

1. Go to [developers.facebook.com](https://developers.facebook.com) → your app → **WhatsApp → Configuration**
2. Set **Callback URL** to `https://<your-ngrok-url>/webhook`
3. Set **Verify token** to the value of `WA_VERIFY_TOKEN` in your `.env` (default: `sugarrush_verify`)
4. Click **Verify and Save**, then subscribe to the **messages** webhook field
5. Subscribe your app to the WhatsApp Business Account:
   ```bash
   curl -X POST "https://graph.facebook.com/v20.0/<WABA_ID>/subscribed_apps" \
     -H "Authorization: Bearer <WA_TOKEN>"
   ```
6. On the **API Setup** page, add your personal WhatsApp number to the test recipient list
7. Send any command to the test number from WhatsApp

### Test without WhatsApp (HTTP endpoints)

```bash
# Full scout pipeline — returns JSON report
curl -X POST http://localhost:8000/run/scout

# Any other command
curl -X POST http://localhost:8000/run/alerts
curl -X POST http://localhost:8000/run/pricing
curl -X POST http://localhost:8000/run/opportunities

# Retrieve the latest stored report
curl http://localhost:8000/report/latest?command=scout

# Health check
curl http://localhost:8000/health
```

All endpoints documented at `http://localhost:8000/docs` (FastAPI auto-docs).

### Optional: Deploy to Render / Railway (stable public URL)

Push to GitHub, create a web service, set all env vars, and set the start command:
```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
Point the Meta webhook at `https://<your-service-url>/webhook`.

---

## Architecture

```
WhatsApp user ──▶ Meta WhatsApp Cloud API ──▶ POST /webhook (FastAPI)
                                                      │
                                                      ├─ parse command from message body
                                                      ├─ ack immediately: {"status": "ok"}
                                                      └─ schedule BackgroundTasks job ──────┐
                                                                                            ▼
                                                                                    pipeline.run(command)
                                                                                            │
        ┌───────────────────────────────────────────────────────────────────────────────────┤
        ▼                  ▼                   ▼                    ▼                       │
   discovery.py      firecrawl_scraper   instagram_scraper    places_scraper               │
   (confirm seed     (sites, menus,      (Apify: IG public    (Google reviews,             │
    + discover        search, news)       posts/engagement)    ratings, branches)          │
    new ones)                                                                               │
        └───────────────────────────────┬───────────────────────────────────────────────────┘
                                        ▼
                                  cleaning.py  (dedup, normalize, noise filter)
                                        ▼
                                     db.py  (store raw + cleaned findings, run row)
                                        ▼
                                  analysis.py  (Groq: per-finding enrichment + report)
                                        ▼
                                  send.py  (Meta Graph API, chunked ≤1500 chars)
                                        ▼
                               WhatsApp user receives full report
```

**Why the async pattern is mandatory:** Meta expects the webhook HTTP response within seconds. A real scrape across 3 sources takes 30–60 seconds. The handler returns `{"status": "ok"}` immediately and processes in a `BackgroundTasks` job, then pushes the final report back via the Meta Graph API.

---

## How Scraping / Fetching Works

All competitor data is fetched programmatically at run time. The seed list contains only names, handles, and URLs as pointers — all content is always fetched live.

### Data Sources

| Source | Tool | What we fetch |
|---|---|---|
| Competitor websites & menus | Firecrawl (`firecrawl-py`) | Homepage markdown, menu/offer pages, new product text |
| Web search / news | Firecrawl `/search` | Recent launches, promotions, news mentions, competitor discovery |
| Instagram public posts | Apify (`apify-client`, actor: `apify/instagram-post-scraper`) | Captions, like/comment counts, timestamps, media URLs |
| Google Maps ratings & reviews | Google Places API (New) Text Search | Ratings, review counts, review text, branch locations |
| AI analysis | Groq (`llama-3.3-70b-versatile` via OpenAI-compatible SDK) | Per-finding summaries, relevance scores 1–10, full report |

### Firecrawl
Used for Google-style web search (competitor discovery, news searches like "Baskin Robbins new flavor Islamabad") and scraping competitor websites and menu pages. Handles JS rendering and basic anti-bot protection. Cannot scrape Instagram — that is handled by Apify.

### Apify (Instagram)
Uses the `apify/instagram-post-scraper` actor to fetch recent public posts from competitor profiles. Returns captions, engagement counts, timestamps, and media URLs. Public profiles only — no logins, cookies, or private account access.

### Google Places API (New)
Text Search endpoint returns ratings, review counts, recent review text, and branch addresses for each competitor. Multiple distinct addresses trigger a `branch_update` finding.

### Groq (AI analysis)
Findings are batched in groups of up to 15 and sent to `llama-3.3-70b-versatile`. Each batch returns `{id, summary, relevance_score}` per finding. A second call generates the command-specific report from the top enriched findings. Falls back to `llama-3.1-8b-instant` → `gemma2-9b-it` on rate limits.

---

## Competitor Selection — Rationale

Sugar Rush (Kohsar Market, F-6) is a dessert/ice cream shop competing for Islamabad foot traffic and social media mindshare. The seed competitors were selected to cover three strategic tiers:

**1. Direct ice-cream rival**
- **Baskin Robbins Pakistan** (`baskinrobbinspk`) — the most prominent branded ice cream chain with Islamabad branches. Customers directly compare it to Sugar Rush.

**2. High-engagement cake/dessert content leaders**
- **Layers** (`layers.bakeshop`) — large IG following, cake-led content, sets content trends
- **Tehzeeb Bakers** (`tehzeeb.pk`) — G-9 + multiple branches, strong bakery presence

**3. Local dessert-café cluster** (same Islamabad foot traffic, same customer occasions)
- **Burning Brownie** (Beverly Centre, F-6/1) — cheesecakes/brownies, same neighborhood
- **Kitchen Cuisine** (F-10) — Ferrero Rocher cakes, custom orders
- **Loafology Bakery & Café** (Blue Area / F-11) — strong promo activity
- **O'Brownies** — brownie-focused, similar target demographic

Competitors without pre-confirmed Instagram handles are resolved at runtime via Firecrawl search and stored in the DB. The discovery layer also finds up to 3 new competitors per `scout` run dynamically.

---

## Caching / Freshness Strategy

- `scout` → always triggers a **live fetch** across all three sources
- All other commands → reuse the most recent run's findings if under `FRESHNESS_MINUTES` (default 90 minutes). If stale, triggers a fresh fetch first
- Every response includes a freshness note: `Data: live this run` or `Data: last run, X minutes ago`
- Raw JSON from every run is saved to `data/raw/<run_id>_all_raw.json` for inspection

This gives genuine on-demand freshness without burning API credits on every single message.

---

## Database Schema (SQLite via SQLAlchemy)

| Table | Purpose |
|---|---|
| `competitors` | Competitor registry (seed + dynamically discovered), with resolved handles and Place IDs |
| `runs` | One row per pipeline execution; tracks status (`ok`/`partial`/`error`), sources ok/failed, finding count |
| `findings` | One row per competitor signal (post, review, web mention); includes AI summary + relevance score + content hash for dedup |
| `reports` | Stored report text per run + command |

---

## Project Structure

```
sugar-rush-scout/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── run.sh
├── app/
│   ├── config.py              # env loading + COMPETITORS seed list
│   ├── db.py                  # SQLAlchemy models + session + init_db()
│   ├── schemas.py             # Pydantic FindingSchema
│   ├── discovery.py           # Confirm seed competitors + discover new ones
│   ├── pipeline.py            # Orchestrator: run(command) → report text
│   ├── cleaning.py            # Dedup, normalize, noise filter, SHA1 content hashing
│   ├── analysis.py            # Groq: per-finding enrichment + build_report()
│   ├── send.py                # Meta WhatsApp send helper + chunking
│   ├── main.py                # FastAPI: /webhook, /run/{command}, /health, /report/latest
│   └── scrapers/
│       ├── firecrawl_scraper.py   # search + site/menu/news scrape
│       ├── instagram_scraper.py   # Apify IG actor
│       └── places_scraper.py      # Google Places text search + reviews
├── data/
│   ├── raw/                   # JSON dumps of every raw fetch (one file per run)
│   └── sample_report.md       # Real generated report from a live run
├── tests/
│   ├── test_cleaning.py       # 21 tests — dedup, noise filter, normalization
│   ├── test_pipeline_smoke.py # 4 tests — orchestration with mocked sources
│   └── test_commands.py       # 20 tests — all 8 commands return correct output
└── scout.db                   # SQLite (gitignored)
```

---

## Limitations

- **Instagram** is the richest signal but the most fragile. We use Apify on **public** profiles only with small post limits to stay within free tier. Private accounts, stories, and DMs are out of scope by design.
- **Foodpanda** menus/listings are heavily bot-protected. Firecrawl attempts best-effort; if blocked, the run continues with website + Instagram + Google reviews.
- **Facebook** public pages are inconsistently accessible; treated as best-effort.
- **Pricing** is only reported where a competitor publishes a public menu or price page. The agent says "price data not found" rather than inventing numbers.
- Free-tier rate and credit limits cap how many competitors and posts are pulled per run (configurable via env vars). The freshness/caching strategy keeps this sustainable.
- **Groq free tier** has a 100k tokens/day limit. A full `scout` run with 100+ findings uses most of this. Fallback models (`llama-3.1-8b-instant`, `gemma2-9b-it`) kick in automatically on rate limits.
- Everything uses **public data only**. No logins, no private accounts, no paywalls, no platform-protection bypassing.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI + Uvicorn |
| Storage | SQLite via SQLAlchemy 2.x |
| Web search + scraping | Firecrawl (`firecrawl-py`, `V1FirecrawlApp`) |
| Instagram | Apify (`apify-client`, actor `apify/instagram-post-scraper`) |
| Google Maps | Google Places API (New) Text Search |
| AI analysis | Groq via OpenAI-compatible SDK (`llama-3.3-70b-versatile`) |
| WhatsApp | Meta WhatsApp Cloud API |
| Dev tunnel | ngrok |
| Retries | tenacity (3 attempts, exponential backoff on all external calls) |
