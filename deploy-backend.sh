#!/bin/bash
# Deploy Hold Em or Fold Em backend to Google Cloud Run
set -e

PROJECT_ID="${GCP_PROJECT_ID:-ttb-lang1}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="holdemfoldem-api"
MCP_SRC="/Users/adamaslan/code/gcp-app-w-mcp1/mcp-finance1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🃏 Deploying Hold Em or Fold Em backend..."
echo "   Project : $PROJECT_ID"
echo "   Region  : $REGION"
echo "   Service : $SERVICE"
echo ""

# ── Build context ─────────────────────────────────────────────────────────────
# The Dockerfile COPYs:
#   cloud-run/environment.yml  →  from holdemfoldemapp/backend/cloud-run/
#   cloud-run/main.py          →  from holdemfoldemapp/backend/cloud-run/
#   src/                       →  from mcp-finance1/src/
#   fibonacci/                 →  from mcp-finance1/fibonacci/
#
# Strategy: create a temp build context that merges both source trees.

BUILD_CTX=$(mktemp -d)
trap "rm -rf $BUILD_CTX" EXIT

# Copy mcp-finance1 source (src/ and fibonacci/)
cp -r "$MCP_SRC/src"       "$BUILD_CTX/src"
cp -r "$MCP_SRC/fibonacci" "$BUILD_CTX/fibonacci" 2>/dev/null || true

# Copy cloud-run assets (Dockerfile, environment.yml) + v5 main.py
mkdir -p "$BUILD_CTX/cloud-run"
cp "$SCRIPT_DIR/backend/cloud-run/Dockerfile"       "$BUILD_CTX/Dockerfile"
cp "$SCRIPT_DIR/backend/main.py"                    "$BUILD_CTX/cloud-run/main.py"
cp "$SCRIPT_DIR/backend/cloud-run/environment.yml"  "$BUILD_CTX/cloud-run/environment.yml"

echo "📦 Build context prepared at $BUILD_CTX"
ls "$BUILD_CTX"

# ── Deploy ────────────────────────────────────────────────────────────────────
cd "$BUILD_CTX"

# API keys are stored in GCP Secret Manager (never passed as plain env vars)
# Secrets must exist: FINNHUB_API_KEY, ALPHA_VANTAGE_KEY, GEMINI_API_KEY
# To create/update: gcloud secrets versions add SECRET_NAME --data-file=-

gcloud run deploy "$SERVICE" \
    --source . \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --allow-unauthenticated \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID" \
    --set-secrets="FINNHUB_API_KEY=FINNHUB_API_KEY:latest,ALPHA_VANTAGE_KEY=ALPHA_VANTAGE_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest" \
    --memory=1Gi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=10 \
    --quiet

# ── Print URL ─────────────────────────────────────────────────────────────────
SERVICE_URL=$(gcloud run services describe "$SERVICE" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='value(status.url)')

echo ""
echo "✅ Deployed!"
echo "   URL: $SERVICE_URL"
echo ""
echo "Test:"
echo "  curl $SERVICE_URL/health"
echo "  curl -X POST $SERVICE_URL/api/analyze -H 'Content-Type: application/json' -d '{\"symbol\":\"AAPL\"}'"
echo ""
echo "Set this in your frontend .env.local:"
echo "  BACKEND_URL=$SERVICE_URL"
