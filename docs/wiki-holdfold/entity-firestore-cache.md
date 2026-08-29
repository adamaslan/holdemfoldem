---
date: 2026-05-31
type: entity
tags: [cache, firestore, gcp, performance]
sources: [../backend/main.py, ../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/cache/firestore_cache.py]
---

# Entity: Firestore Cache

Wraps the signal pipeline in a write-through Firestore cache. Avoids re-running 18 detectors + yfinance fetches on repeated requests for the same ticker. **Note:** despite earlier descriptions, the holdfold `_cached_or_fetch` does *not* implement true stale-while-revalidate — on a stale hit it logs and then `await`s a fresh fetch synchronously (blocking the request), rather than returning the stale value and refreshing in the background. Only fresh hits are served without a re-fetch.

## What it is

Implemented in `backend/main.py` via `_cached_or_fetch()` and backed by `MCPFirestoreCache` from `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/cache/firestore_cache.py`.

**Cache key**: the bare `symbol` string, passed verbatim as the `cache_key` argument in all three `_cached_or_fetch` calls in `backend/main.py` (lines 1165–1167). It does **not** include `period`, `options_hash`, or any schema version. The Firestore doc path is `mcp_tool_cache/{tool_name}/results/{symbol}` (`firestore_cache.py:88-93`). Because `period` is absent from the key, a cached `AAPL` result for `1mo` is served for a subsequent `AAPL` request at `1y` — a confirmed cross-period collision. `CACHE_SCHEMA_VERSION = "v2"` is defined in `gcp-app-w-mcp1/.../config.py:209` but is not referenced by either the holdfold wrapper or `firestore_cache.py`.

**TTL**: `_FIRESTORE_CACHE_TTL_SECONDS = 3600` (1 hour). On a stale hit (`age ≥ TTL`), `_cached_or_fetch` logs "cache stale ... refetching" and falls through to a **synchronous** `await fetch_fn()` (`main.py:111-117`) — the caller waits for the fresh result. There is no background-refresh task in this wrapper.

**Initialization**: `_get_firestore()` uses a module-level singleton pattern with a lazy init and a boolean `False` sentinel for "unavailable". If Firestore credentials are missing (common in local dev without GCP creds), the cache silently degrades to pass-through — every request runs the full pipeline.

**Read path**:
```
_cached_or_fetch(tool_name, cache_key, fetch_fn)
  1. Read Firestore doc for cache_key
  2. If hit + fresh (age < TTL): return doc["result"]
  3. If hit + stale: log + fall through (NO early return) → await fetch_fn() synchronously; rewrite
  4. If miss: await fetch_fn(); write to Firestore; return result
```

**Write path**: `fs.write_tool_result(tool_name, cache_key, result)` — always writes after a fresh pipeline run.

## Where used

- [[entity-backend-api]] — `_cached_or_fetch` is the outermost wrapper in `/api/analyze`
- [[entity-signal-pipeline]] — the `analyze_security` call is what gets cached

## Known failures

1. **Firestore unavailable in local dev** — if no GCP credentials are present, `MCPFirestoreCache()` raises and `_firestore` is set to `False`. All requests run the full pipeline (slow but functional). No user-visible error — just no caching.
2. **Cache key does not include `SCHEMA_VERSION`** — confirmed: neither `backend/main.py` nor `firestore_cache.py` injects `CACHE_SCHEMA_VERSION`. If detector logic or scoring changes, stale cached verdicts with the old schema can be returned for up to 1 hour.
3. **Cache key does not include `period`** — confirmed: the cache key is the bare `symbol`. A cached result for one period is returned for any other period of the same symbol until the TTL expires. This is a correctness bug, not just a staleness window.
4. **Stale hits block the caller** — the wrapper has no background refresh; a stale hit triggers a synchronous re-fetch, so the request that finds a stale entry pays the full pipeline latency. The "stale-while-revalidate" framing in earlier docs did not match the code.

## Open questions

- Should TTL be split by period? `config.py` already defines `CACHE_TTL_INTRADAY_SECONDS = 300` (5 min) and `CACHE_TTL_DAILY_SECONDS = 3600` (1 h) plus an `INTRADAY_PERIODS` frozenset, but the holdfold wrapper ignores them and uses a flat `_FIRESTORE_CACHE_TTL_SECONDS = 3600` for all periods.

## See also

- [[entity-backend-api]] — the API layer that calls this cache
- [[entity-signal-pipeline]] — what gets cached
- [[decision-mcp-finance-as-shared-lib]] — why `MCPFirestoreCache` lives in a sibling repo
