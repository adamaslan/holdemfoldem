"""
Hold Em or Fold Em — Cloud Run entry point.
Runs on port 8080 inside a mambaorg/micromamba container.
"""

import asyncio
import logging
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# src/ is copied to /app/src in the Docker image
sys.path.insert(0, "/app")

from technical_analysis_mcp.server import analyze_security, get_trade_plan  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Hold Em or Fold Em", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    symbol: str
    period: str = "3mo"
    asset_type: str = "stock"


def _build_verdict(analysis: dict, trade: dict) -> dict:
    symbol = analysis["symbol"]
    price = analysis.get("price", 0.0)
    sig_summary = analysis.get("summary", {})
    bullish = sig_summary.get("bullish", 0)
    bearish = sig_summary.get("bearish", 0)
    avg_score = sig_summary.get("avg_score", 50)

    plans = trade.get("trade_plans", [])
    plan = plans[0] if plans else {}
    has_trades = trade.get("has_trades", False)

    entry = plan.get("entry_price")
    stop = plan.get("stop_price")
    target = plan.get("target_price")
    rr = plan.get("risk_reward_ratio")
    bias = plan.get("bias", "neutral")

    if has_trades and bias == "bullish" and avg_score >= 60:
        verdict, confidence = "HOLD EM", min(avg_score, 95)
    elif has_trades and bias == "bearish" and avg_score >= 60:
        verdict, confidence = "FOLD EM", min(avg_score, 95)
    elif bullish > bearish and avg_score >= 55:
        verdict, confidence = "HOLD EM", avg_score
    elif bearish > bullish and avg_score >= 55:
        verdict, confidence = "FOLD EM", avg_score
    else:
        verdict, confidence = "NEUTRAL", 50.0

    summary_parts = [
        f"{bullish} bullish / {bearish} bearish signals.",
        f"Avg signal score: {avg_score:.0f}/100.",
    ]
    if has_trades and plan and all([entry, stop, target, rr]):
        summary_parts.append(
            f"Trade plan: entry ${entry}, stop ${stop}, target ${target} (R/R {rr:.2f})."
        )

    return {
        "symbol": symbol,
        "verdict": verdict,
        "confidence": round(confidence, 1),
        "price": price,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_reward": rr,
        "bias": bias,
        "top_signals": analysis.get("signals", [])[:5],
        "summary": " ".join(summary_parts),
    }


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    symbol = req.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    logger.info("Analyzing %s (%s) period=%s", symbol, req.asset_type, req.period)

    try:
        analysis, trade = await asyncio.gather(
            analyze_security(symbol, period=req.period),
            get_trade_plan(symbol, period=req.period),
        )
    except Exception as e:
        logger.error("Analysis failed for %s: %s", symbol, e)
        raise HTTPException(status_code=503, detail=f"Analysis failed: {e}")

    return _build_verdict(analysis, trade)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
