---
date: 2026-05-31
type: entity
tags: [ai-council, rag, frontend, proxy]
sources: [../frontend/src/app/api/council/route.ts, ../frontend/src/components/AiCouncilCommentary.tsx, ../docs/ai-council-integration.md]
---

# Entity: AI Council Proxy (`/api/council` + `AiCouncilCommentary.tsx`)

A two-file integration that adds AI Council commentary on verdicts — a thin Next.js proxy route plus a React component. Forwards the resolved `HoldFoldVerdict` as a structured prompt to the ai-text-opt-1024 RAG backend and renders the answer with source chips.

## What it is

**`frontend/src/app/api/council/route.ts`**

Proxies `POST /api/council` → `COUNCIL_URL/api/chat` (ai-text-opt-1024, default `:3001`). Same pattern as the `analyze` proxy. Returns 503 with a descriptive message if the Council backend is unreachable.

Request forwarded:
```json
{ "message": "<built prompt string>", "trader_filter": null }
```

Response passed through:
```json
{
  "answer": "string",
  "llm_provider": "gemini" | "mistral",
  "sources": [{ "text_preview": "...", "source_file": "...", "rerank_score": 0.88 }],
  "context_empty": false
}
```

**`frontend/src/components/AiCouncilCommentary.tsx`**

Accepts the resolved `HoldFoldVerdict` as a prop. The component:
1. Builds a structured prompt from verdict fields (`top_signals`, `rsi`, `macd`, `adx`, `atr`, `primary_signal`, `supporting_signals`, `verdict`, `confidence`, `bias`, `risk_level`, `volatility_regime`)
2. Renders an "Ask the Council" button (disabled until verdict is resolved)
3. On tap: POST to `/api/council`, renders `answer` text + source chips (`source_file · rerank_score`)
4. If `context_empty: true`: shows a yellow warning that the answer is from general LLM knowledge, not the RAG corpus

Trigger model: **manual tap only** — consistent with `gcp3-mobile`'s `concept-council-tap-in` rule (cross-repo; not a page in this wiki). No auto-fire on verdict change.

**Prompt shape**:
```
Verdict for {symbol}: {verdict} @ {confidence}% confidence.
Bias: {bias}. Risk: {risk_level}. Vol regime: {volatility_regime}.
Top signals: {top 5 signals with strength}.
Indicators — RSI: {rsi}, MACD: {macd}, ADX: {adx}, ATR: {atr}.
Primary: {primary_signal}. Supporting: {supporting_signals}.

As an AI trading council, comment on whether these signals justify the {verdict} verdict.
Identify the strongest supporting evidence and the biggest counter-argument. Be concise (~150 words).
```

## Where used

- [[entity-frontend-app]] — `AiCouncilCommentary` is rendered in `page.tsx` inside the `{verdict && (...)}` block
- ai-text-opt-1024 RAG backend — the upstream service this proxy forwards to

## Known failures

1. **ai-text-opt-1024 must be running locally** — no deployed URL configured for production. The "Ask the Council" feature is dev-only unless `COUNCIL_URL` is set to a deployed instance.
2. **No deduplication** — asking again on the same verdict fires a new LLM call even if the verdict is unchanged. Each tap burns a Gemini call.
3. **`COUNCIL_URL` not set in production** — if `COUNCIL_URL` is missing, the proxy falls back to `http://localhost:3001`, which is always unreachable in a deployed context.

## Open questions

- Should the council answer be memoized by `hash(symbol + verdict + top_signals)` to avoid duplicate LLM calls on re-render?
- Should `trader_filter` be exposed in the UI? Passing `"T1"` or `"T2"` would scope the RAG corpus to short-term vs long-term trader notes (the same pattern used in `gcp3-mobile`'s `concept-dual-view-chat`, cross-repo).

## See also

- [[entity-frontend-app]] — the parent UI that renders this component
- [[entity-backend-api]] — the verdict source that feeds the prompt
- [[decision-council-proxy-not-direct]] — why this is a Next.js proxy rather than a new Python endpoint
- `gcp3-mobile/docs/wiki-mobile/concept-council-tap-in.md` — the shared "tap-to-ask" philosophy
