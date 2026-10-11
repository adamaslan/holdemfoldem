"""
Hold Em or Fold Em — FastAPI HTTP adapter.

The verdict engine itself lives in core.py so the CLI and MCP server can call
it without importing FastAPI. This module only translates HTTP concerns
(status codes, request-id header, CORS) on top of core.compute_verdict().
"""

import logging
import os
import uuid

from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Must import before core: core.py chdirs into mcp-finance1 at import time, after
# which sibling modules in this directory are no longer importable by name.
from signals_client import SignalsUnavailableError, fetch_dip_study, fetch_swing_grid  # noqa: I001
from core import (
    AnalysisUnavailableError,
    AnalyzeRequest,
    HoldFoldVerdict,
    VerdictParams,
    check_backend_health,
    compute_verdict,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Hold Em or Fold Em", version="5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=HoldFoldVerdict)
async def analyze(req: AnalyzeRequest, response: Response) -> HoldFoldVerdict:
    request_id = str(uuid.uuid4())
    response.headers["X-Request-Id"] = request_id

    try:
        return await compute_verdict(req, request_id=request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AnalysisUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/params")
async def params() -> dict[str, Any]:
    """Verdict thresholds: defaults and bounds, for building override requests."""
    schema = VerdictParams.model_json_schema()
    return {"defaults": VerdictParams().model_dump(), "schema": schema["properties"]}


class ThesisRequest(BaseModel):
    analyze: AnalyzeRequest
    dip_period: str = "5y"
    dip_params: dict[str, Any] = Field(default_factory=dict)
    swing_params: dict[str, Any] | None = Field(
        default=None,
        description="Set (even to {}) to also run signals-app's swing_grid op; omitted = skipped.",
    )
    swing_period: str = "5y"


@app.post("/api/thesis")
async def thesis(req: ThesisRequest, response: Response) -> dict[str, Any]:
    """Verdict plus signals-app's dip-timing study for the same ticker.

    The verdict is required; the dip study is best-effort. If signals-app is
    unset or down, ``dip_study`` is null and ``warnings`` says why rather
    than failing the whole call.
    """
    request_id = str(uuid.uuid4())
    response.headers["X-Request-Id"] = request_id
    try:
        verdict = await compute_verdict(req.analyze, request_id=request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except AnalysisUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    warnings: list[str] = []
    dip_study = None
    try:
        dip_study = await fetch_dip_study(
            verdict.symbol, period=req.dip_period, params=req.dip_params
        )
    except SignalsUnavailableError as e:
        logger.warning("request_id=%s dip study unavailable: %s", request_id, e)
        warnings.append(f"dip_study_unavailable: {e}")
    swing = None
    if req.swing_params is not None:
        try:
            swing = await fetch_swing_grid(
                verdict.symbol, period=req.swing_period, params=req.swing_params
            )
        except SignalsUnavailableError as e:
            logger.warning("request_id=%s swing grid unavailable: %s", request_id, e)
            warnings.append(f"swing_unavailable: {e}")
    return {
        "verdict": verdict.model_dump(),
        "dip_study": dip_study,
        "swing": swing,
        "warnings": warnings,
    }


@app.get("/health")
async def health():
    return await check_backend_health()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
