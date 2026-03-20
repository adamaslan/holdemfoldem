---
name: health-check
description: Check health of all Hold Em / Fold Em components (Next.js frontend on :3001, FastAPI backend, fin-ai1 mamba env)
---

Perform a comprehensive health check of the Hold Em / Fold Em system.

## System Health Check

### 1. Frontend Health (Next.js on port 3001)
```bash
cd /Users/adamaslan/code/holdemfoldemapp/frontend

# Check if dev server is running
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001 | grep -q "200\|304" && echo "✅ Frontend dev server: Running (localhost:3001)" || echo "⚠️  Frontend dev server: Not running (start with: npm run dev)"

# Check node_modules
[ -d "node_modules" ] && echo "✅ node_modules: Installed" || echo "❌ node_modules: Missing (run: npm install)"
```

### 2. Backend Health (FastAPI on port 8000)
```bash
# Check if local backend is running
curl -s http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ Backend: Running -', d)" 2>/dev/null || \
  curl -s http://localhost:8000/ 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ Backend: Running -', d)" 2>/dev/null || \
  echo "⚠️  Backend: Not running (activate fin-ai1 & run: python3 backend/cloud-run/main.py)"
```

### 3. Mamba Environment (fin-ai1)
```bash
# Check mamba/micromamba available
mamba --version > /dev/null 2>&1 && echo "✅ Mamba: $(mamba --version)" || echo "❌ Mamba: Not available"

# Check fin-ai1 environment exists
source ~/.zshrc 2>/dev/null
conda env list 2>/dev/null | grep -q "fin-ai1" && echo "✅ fin-ai1 env: Exists" || echo "❌ fin-ai1 env: Missing (run: mamba env create -f backend/cloud-run/environment.yml)"

# Check key Python packages inside fin-ai1
source ~/.zshrc 2>/dev/null && conda activate fin-ai1 2>/dev/null && python3 -c "
import fastapi, uvicorn, pydantic
print('✅ Backend Python packages: fastapi, uvicorn, pydantic — OK')
" || echo "❌ Backend Python packages: Missing (activate fin-ai1 and check environment.yml)"
```

### 4. GCP / Shared Services
```bash
# Check gcloud auth
gcloud auth list --filter="status=ACTIVE" --format="value(account)" 2>/dev/null | grep -q "@" && \
  echo "✅ GCP Auth: $(gcloud auth list --filter='status=ACTIVE' --format='value(account)' 2>/dev/null | head -1)" || \
  echo "❌ GCP Auth: Not authenticated (run: gcloud auth login)"

# Check the shared mcp-finance1 .env that backend reads at startup
ENV_PATH="/Users/adamaslan/code/gcp-app-w-mcp1/mcp-finance1/.env"
[ -f "$ENV_PATH" ] && echo "✅ Shared mcp-finance1 .env: Found" || echo "⚠️  Shared mcp-finance1 .env: Not found at $ENV_PATH"

# Check shared mcp-finance1 src is importable (backend depends on it)
[ -d "/Users/adamaslan/code/gcp-app-w-mcp1/mcp-finance1/src" ] && echo "✅ mcp-finance1/src: Found" || echo "❌ mcp-finance1/src: Missing — backend will fail to start"
```

### 5. Quick One-liner
```bash
echo "Frontend : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3001 2>/dev/null || echo DOWN)"
echo "Backend  : $(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/ 2>/dev/null || echo DOWN)"
echo "Disk     : $(df -h /Users/adamaslan/code/holdemfoldemapp | tail -1 | awk '{print $5 " used, " $4 " free"}')"
```

## Health Summary Dashboard

```
╔═══════════════════════════════════════════╗
║   HOLD EM / FOLD EM HEALTH CHECK REPORT   ║
╚═══════════════════════════════════════════╝

Date: <today>

COMPONENT STATUS:
─────────────────────────────────────────────
  Frontend (Next.js :3001)  : ✅/⚠️
  Backend (FastAPI :8000)   : ✅/⚠️
  fin-ai1 mamba env         : ✅/❌
  GCP Auth                  : ✅/❌
  Shared mcp-finance1 src   : ✅/❌
─────────────────────────────────────────────
```

## Fix Suggestions

**Frontend not running:**
```bash
cd /Users/adamaslan/code/holdemfoldemapp/frontend && npm run dev
```

**node_modules missing:**
```bash
cd /Users/adamaslan/code/holdemfoldemapp/frontend && npm install
```

**Backend not running:**
```bash
source ~/.zshrc && mamba activate fin-ai1
python3 /Users/adamaslan/code/holdemfoldemapp/backend/cloud-run/main.py
```

**fin-ai1 env missing:**
```bash
mamba env create -f /Users/adamaslan/code/holdemfoldemapp/backend/cloud-run/environment.yml
```

**GCP not authenticated:**
```bash
gcloud auth login
gcloud auth application-default login
```

## When to Run

- ✅ Before starting development
- ✅ After pulling code changes
- ✅ When debugging issues
- ✅ Before deploying

---

**Dev workflow**: `/health-check` → `npm run dev` (frontend) + `mamba activate fin-ai1 && python3 backend/cloud-run/main.py` (backend) in separate terminals.
