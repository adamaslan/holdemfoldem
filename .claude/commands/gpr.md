# Deploy + PR

Runs secret scan, tests the backend, deploys the holdemfoldem v5 backend to Cloud Run via `deploy-backend.sh`, then creates a **brand new branch**, commits all changes, and opens a PR against `github.com/adamaslan/holdemfoldem`.

> **Scope**: Full-stack — `backend/` and `frontend/` in this repo. For mcp-finance1 backend changes, use `/gpr` in that repo.

## Steps

1. All git operations run from `/Users/adamaslan/code/holdemfoldemapp`
2. Checkout a fresh branch off `main` — never reuse the current branch
3. **Secret scan ALL changed files BEFORE staging** — hard stop if any secrets found
4. Stage only clean files by name — never `git add .` or `git add -A`
5. Run a quick backend smoke test against the running v5 backend (port 8001)
6. Deploy backend to Cloud Run via `deploy-backend.sh` and confirm healthy
7. If any step fails, diagnose and fix before continuing
8. Commit — the pre-commit hook will re-scan and block if anything slipped through
9. Push to remote
10. Create a PR against `main`

## Secret Scanning Rules

**These are hard blockers — stop immediately if any are violated.**

### Never stage or commit
- `.env`, `.env.local`, `.env.*` — all env files (gitignored, contain API keys)
- `*.key`, `*.pem`, `*.p12`, `*.pfx` — private key files
- `credentials.json`, `service-account*.json`, `*-key.json` — GCP credential files
- `terraform.tfvars` — contains real GCP project values
- Any file containing these patterns:
  - `AIzaSy[A-Za-z0-9_-]{35}` — GCP/Gemini API key
  - `GOCSPX-[A-Za-z0-9_-]{24,}` — GCP OAuth secret
  - `ya29\.[A-Za-z0-9_-]{100,}` — GCP access token
  - `d66cl2hr01` — Finnhub API key prefix
  - `DSQINJ3N` — Alpha Vantage key prefix
  - `sk_live_[A-Za-z0-9]{24,}` — Stripe secret key

### If a secret is found in a file
1. Do NOT stage the file
2. Replace the hardcoded value with `os.getenv("KEY_NAME")` or `process.env.KEY_NAME`
3. The actual value belongs in `.env.local` (frontend) or passed as a Cloud Run env var (backend)
4. Re-scan, then stage only after clean

### Never use `--no-verify`
The pre-commit hook is a safety net. If it blocks, fix the underlying issue.

## Execute

All commands run from the repo root (wherever `deploy-backend.sh` lives).

```bash
# 0. Enter repo root (use git root, not a hardcoded path)
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

# 1. Checkout a brand new branch off main
git checkout main
git pull origin main
git checkout -b <feature|fix|refactor>/<short-description>

# 2. Secret scan ALL changed files BEFORE staging — stop if anything hits
git diff --name-only HEAD | xargs -I{} sh -c \
  'grep -lE "AIzaSy[A-Za-z0-9_-]{35}|GOCSPX-[A-Za-z0-9_-]{24,}|d66cl2hr01[A-Za-z0-9]{5,}|DSQINJ3N[A-Za-z0-9]{3,}|sk_live_[A-Za-z0-9]{24,}" {} 2>/dev/null && echo "🚨 SECRET FOUND in {}" || true'

# 3. Stage only clean files — add by name, never git add . or git add -A
git add backend/main.py backend/cloud-run/ frontend/src/ frontend/e2e/ deploy-backend.sh
# Verify nothing sensitive snuck in:
git diff --cached --name-only

# 4. Quick smoke test — confirm v5 backend is up and responding
curl -s http://localhost:8001/health | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('✅ Backend healthy:', d) if d.get('version')=='5.0' else print('⚠️ Unexpected response:', d)" \
  || echo "⚠️  Backend not running — start with: uvicorn backend.main:app --port 8001"

# Test a real analyze call
curl -s http://localhost:8001/api/analyze \
  -X POST -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","period":"1mo"}' | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('✅ Analyze OK — verdict:', d.get('verdict')) if 'verdict' in d else print('❌ Analyze failed:', d)"

# 5. Deploy backend to Cloud Run
bash deploy-backend.sh

# 6. Confirm Cloud Run service is healthy (deploy-backend.sh prints the URL)
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-$(gcloud config get-value run/region 2>/dev/null || echo us-central1)}"
SERVICE_URL=$(gcloud run services describe holdemfoldem-api \
  --region "$REGION" --project "$PROJECT_ID" \
  --format='value(status.url)' 2>/dev/null)
echo "Service URL: $SERVICE_URL"
curl -s "$SERVICE_URL/health" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('✅ Cloud Run healthy:', d)" \
  || echo "❌ Cloud Run health check failed"

# 7. If deploy fails — check logs and fix before committing
gcloud run services logs read holdemfoldem-api \
  --project "$PROJECT_ID" --region "$REGION" --limit 30

# 8. Commit — pre-commit hook re-scans automatically
git commit -m "$(cat <<'EOF'
type(scope): description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"

# 9. Push
git push -u origin HEAD

# 10. Create PR against holdemfoldem main
gh pr create \
  --repo adamaslan/holdemfoldem \
  --title "short title under 70 chars" \
  --body "$(cat <<'EOF'
## Summary
- bullet points of what changed

## Test plan
- [ ] Secret scan passed — no API keys, env files, or credentials staged
- [ ] Backend smoke test passed (localhost:8001)
- [ ] `deploy-backend.sh` succeeded
- [ ] Cloud Run `holdemfoldem-api` healthy after deploy
- [ ] Frontend dev server tested against new backend

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Always start from a fresh branch off `main`. Diagnose and fix all secret/test/deploy failures before creating the PR.

> **Frontend deploy**: Vercel deploys automatically on merge to `main`. Set `BACKEND_URL` to the Cloud Run URL in Vercel project environment variables.
