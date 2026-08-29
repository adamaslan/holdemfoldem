"""
Hold Em or Fold Em — FastAPI HTTP adapter.

The verdict engine itself lives in core.py so the CLI and MCP server can call
it without importing FastAPI. This module only translates HTTP concerns
(status codes, request-id header, CORS) on top of core.compute_verdict().
"""

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from core import (
    AnalysisUnavailableError,
    AnalyzeRequest,
    HoldFoldVerdict,
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


@app.get("/health")
async def health():
    return await check_backend_health()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
