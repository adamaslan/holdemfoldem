---
date: 2026-05-31
type: decision
tags: [ranking, gemini, resilience, signals]
sources: [../docs/signal-pipeline.md, ../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/ranking.py]
---

# Decision: Rule-Based Ranking as Always-Available Fallback

## Decision

`RuleBasedRanking` is always the floor for signal scoring. `GeminiRanking` is opt-in (`use_ai=True`) and protected by a circuit breaker; any failure falls through to rule-based.

## Date

Original architecture; documented 2026-05-31.

## Context

The signal pipeline needs to return a verdict even when the Gemini API is unavailable (quota exhausted, network partition, latency spike). Making AI ranking optional ensures the app degrades gracefully rather than returning 503s.

## Alternatives considered

| Alternative | Why not |
|-------------|---------|
| AI ranking always required | Single point of failure; Gemini outage = no verdicts |
| AI ranking disabled by default | Loses the depth of AI scoring in normal operation |
| Separate AI-only and rule-only endpoints | Two APIs to maintain; clients choose which to call |

## Consequences

**Enables:**
- 100% uptime for verdict generation regardless of Gemini status
- The circuit breaker (5 failures / 60s → 5 min open) prevents Gemini timeouts from cascading into pipeline slowdowns

**Rules out:**
- Guaranteed AI-quality scoring in all requests (degraded scoring during outage window)

## Validated by

Circuit breaker logic implemented in `ranking.py` (`_GeminiCircuitBreaker`, a module-level singleton shared across all `GeminiRanking` instances). Thresholds are config constants: `GEMINI_BREAKER_FAILURE_THRESHOLD = 5`, `GEMINI_BREAKER_WINDOW_SECONDS = 60`, `GEMINI_BREAKER_OPEN_SECONDS = 300` (`config.py:204-206`); per-call timeout `GEMINI_TIMEOUT_SECONDS = 4.0`. Any exception in `_rank_with_gemini` (missing API key, breaker open, API error, malformed JSON, or a Gemini score outside `[1, 100]`) falls through to `RuleBasedRanking` (`ranking.py:218-238`, `_apply_scores` drops out-of-range scores). No production incident caused by Gemini unavailability has been recorded.

## See also

- [[entity-signal-pipeline]] — stage 3 (ranking)
- [[entity-mcp-finance]] — `ranking.py` implementation
- [[concept-signal-scoring]] — the rule-based scoring table
