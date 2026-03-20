# Hold Em or Fold Em

Instant **HOLD EM / FOLD EM** verdict for any US stock, ETF, or options ticker.

Combines `analyze_security` (150+ technical signals) + `get_trade_plan` (risk-sized entry/stop/target) from the MCP Finance backend.

## Structure

```
holdemfoldemapp/
├── backend/
│   ├── main.py                    # Local dev FastAPI server (port 8001)
│   └── cloud-run/
│       ├── Dockerfile             # mambaorg/micromamba multi-stage build
│       ├── environment.yml        # mamba deps
│       └── main.py                # Cloud Run entry point (port 8080)
├── frontend/                      # Next.js 16
│   └── src/app/
│       ├── page.tsx               # Single-page UI
│       └── api/analyze/route.ts   # Proxy to backend
├── deploy-backend.sh              # One-command GCP deploy
└── README.md
```

---

## Deploy to GCP Cloud Run

```bash
cd /Users/adamaslan/code/holdemfoldemapp

# Optional overrides (defaults: ttb-lang1 / us-central1)
export GCP_PROJECT_ID=ttb-lang1
export GCP_REGION=us-central1

bash deploy-backend.sh
```

The script:
1. Assembles a temp build context merging `mcp-finance1/src/` + `mcp-finance1/fibonacci/` + `backend/cloud-run/`
2. Runs `gcloud run deploy holdemfoldem-api --source .` (Cloud Build handles the Docker build)
3. Prints the service URL

After deploy, copy the URL into `frontend/.env.local`:
```bash
cp frontend/.env.local.example frontend/.env.local
# Edit BACKEND_URL=https://holdemfoldem-api-xxxx-uc.a.run.app
```

---

## Local Development

### Backend (port 8001)

```bash
source /opt/homebrew/Caskroom/miniforge/base/etc/profile.d/conda.sh
source /opt/homebrew/Caskroom/miniforge/base/etc/profile.d/mamba.sh
mamba activate fin-ai1

cd /Users/adamaslan/code/holdemfoldemapp/backend
uvicorn main:app --reload --port 8001
```

### Frontend (port 3001)

```bash
cd /Users/adamaslan/code/holdemfoldemapp/frontend
npm install
npm run dev   # http://localhost:3001
```

---

## How It Works

1. User enters a ticker + period + asset type
2. Frontend POSTs to `/api/analyze` (Next.js proxy)
3. Next.js proxies to backend (`BACKEND_URL`)
4. Backend runs `analyze_security` + `get_trade_plan` **in parallel** via `asyncio.gather`
5. Verdict: bullish bias + clean trade plan → **HOLD EM** (green), bearish → **FOLD EM** (red)
6. UI shows: verdict, confidence %, price, entry/stop/target, R/R ratio, top 5 signals
