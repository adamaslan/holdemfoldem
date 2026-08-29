---
date: 2026-05-31
type: concept
tags: [signals, scoring, ranking, verdict]
sources: [../docs/signal-pipeline.md, ../../gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/ranking.py]
---

# Concept: Signal Scoring

The rule that translates a signal's text label into a numeric score used by both `RuleBasedRanking` and as a fallback floor for `GeminiRanking`. A score of 60+ on average is required for a HOLD EM / FOLD EM verdict with a trade plan; 55+ for a signal-only verdict.

## The pattern

**Keyword → base score**:

| Strength keyword in signal name | Score |
|--------------------------------|-------|
| EXTREME | 85 |
| STRONG | 75 |
| SIGNIFICANT / VERY | 65 |
| BULLISH / BEARISH | 55 |
| *(default)* | 50 |

The keyword→score map is `STRENGTH_SCORES` and the bonus map is `CATEGORY_BONUSES`, both in `gcp-app-w-mcp1/mcp-finance1/src/technical_analysis_mcp/config.py:92-105`. `_calculate_score` (`ranking.py:160-184`) sets the base score from the **first** matching strength keyword (so a strength label containing both `STRONG` and `BULLISH` scores 75, not 55), then adds the category bonus.

**Category bonus (+10)** for categories considered most reliable: `MA_CROSS`, `MACD`, `VOLUME`.

**Hard ceiling**: 95 (`MAX_RULE_BASED_SCORE`, `config.py:107`). No rule-based signal can score 100 — leaves room for Gemini AI scoring (`[1, 100]`) to rank above rule-based.

**`avg_score`**: mean of the `ai_score` across **all** ranked signals, computed in `analyze_security` (`server.py:699-703`); falls back to `50` when no signals are detected. It is computed *before* the trade-plan suppression pipeline, so suppressions do **not** lower `avg_score` — suppression only governs whether a trade plan is emitted. Drives confidence via four paths:

| Path | Condition | Confidence formula |
|------|-----------|-------------------|
| Trade plan present, score ≥ 60 | has_trade AND bias AND avg_score ≥ 60 | `min(avg_score × 1.05, 95)` |
| Signals-only, score ≥ 55 | bullish/bearish dominance AND avg_score ≥ 55 | `avg_score` |
| Fallback, below 55 | directional dominance but avg_score < 55 | `avg_score × 0.85` |
| Tied / no dominance | bullish_count == bearish_count | `50.0` (hard-coded) |

**Signal collapsing — how `bullish_count` and `bearish_count` are computed**: Each `Signal` object has a `strength` field (e.g. `STRONG_BULLISH`, `BULLISH`, `BEARISH`, `STRONG_BEARISH`). The pipeline counts signals with `BULLISH` in the strength label as bullish, and `BEARISH` as bearish. There is no explicit `is_bullish` flag on each signal — directionality is inferred from the strength keyword. A signal labeled `STRONG_BULLISH` contributes +1 to `bullish_count`. A neutral signal (e.g. `SIGNIFICANT_RANGE`) contributes to neither count but still affects `avg_score`.

**Bearish strategy override**: After the confidence/verdict path above resolves, if `options_strategy ∈ BEARING_STRATEGIES` and the verdict is `HOLD EM`, it is flipped to `FOLD EM`. This override is applied post-confidence — confidence is not recalculated.

**Risk level** derives from avg_score + R/R + ATR%:

| Condition | +points |
|-----------|---------|
| avg_score < 50 | +2 |
| avg_score 50–59 | +1 |
| R/R < 1.5 | +1 |
| ATR% > 3.0% | +1 |
| ATR% > 5.0% | +1 |

Points → risk: 0=low · 1=medium · 2=high · 3+=extreme

## Where it appears

- `RuleBasedRanking` in [[entity-mcp-finance]] — primary implementation
- `GeminiRanking` uses this as a validation floor: AI scores must be in [1, 100]; malformed responses fall back to rule-based
- `_build_verdict` in [[entity-backend-api]] — reads `avg_score` and `bullish`/`bearish` counts from the ranked summary
- `_risk_level` helper in [[entity-backend-api]] — the risk matrix above

## Contradictions / tensions

- The 55 threshold for BULLISH/BEARISH-labeled signals means that any signal explicitly labeled as directional is treated as a weak signal by default. A `MACD BULL CROSS` scores 55 base + 10 category = 65, which is above average — reasonable. But a `RSI OVERSOLD` (a valid contrarian signal) also scores 55 base (no category bonus). Contrarian signals are systematically underscored relative to trend-following signals.
- The `avg_score ≥ 60` gate for HOLD EM with trade plan is easy to clear in trending markets (many signals, high category bonuses) and hard to clear in choppy markets (few signals, lots of 50-default scores). The threshold is not adaptive.
- Category bonus (+10) for `VOLUME` inflates verdicts in high-volume days that may be noise (earnings, index rebalancing). There is no cap on how many volume signals can be included in the avg.

## See also

- [[entity-signal-pipeline]] — stage 3 (ranking) and stage 4 (verdict) implement this scoring
- [[entity-mcp-finance]] — `ranking.py` owns `RuleBasedRanking`
- [[decision-rule-based-ranking-fallback]] — why rule-based is the always-available floor
