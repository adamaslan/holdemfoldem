"use client";
import { useState } from "react";

interface CouncilVerdict {
  symbol: string;
  verdict: "HOLD EM" | "FOLD EM" | "NEUTRAL";
  confidence: number;
  bias: string;
  risk_level: string;
  volatility_regime: string;
  top_signals: { signal: string; strength: string }[];
  rsi: number | null;
  macd: number | null;
  adx: number | null;
  atr: number | null;
  primary_signal: string | null;
  supporting_signals: string[];
}

interface CouncilSource {
  text_preview: string;
  source_file: string;
  chunk_index: number;
  distance: number;
  rerank_score: number;
}

interface CouncilResponse {
  answer: string;
  llm_provider: string;
  sources: CouncilSource[];
  context_empty: boolean;
}

function buildCouncilPrompt(v: CouncilVerdict): string {
  const sigs = v.top_signals
    .slice(0, 5)
    .map((s) => `${s.signal} (${s.strength})`)
    .join(", ");
  const fmt = (n: number | null) => (n === null ? "n/a" : n.toFixed(2));
  return [
    `Verdict for ${v.symbol}: ${v.verdict} @ ${v.confidence}% confidence.`,
    `Bias: ${v.bias}. Risk: ${v.risk_level}. Vol regime: ${v.volatility_regime}.`,
    `Top signals: ${sigs || "none"}.`,
    `Indicators — RSI: ${fmt(v.rsi)}, MACD: ${fmt(v.macd)}, ADX: ${fmt(v.adx)}, ATR: ${fmt(v.atr)}.`,
    `Primary: ${v.primary_signal ?? "—"}. Supporting: ${v.supporting_signals.join(", ") || "—"}.`,
    ``,
    `As an AI trading council, comment on whether these signals and indicators justify the ${v.verdict} verdict. Identify the strongest supporting evidence and the biggest counter-argument. Be concise (~150 words).`,
  ].join("\n");
}

export default function AiCouncilCommentary({ verdict }: { verdict: CouncilVerdict }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<CouncilResponse | null>(null);

  async function askCouncil() {
    setLoading(true);
    setError(null);
    setResponse(null);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30_000);
    try {
      const res = await fetch("/api/council", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          message: buildCouncilPrompt(verdict),
          trader_filter: null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail ?? `Council error ${res.status}`);
        return;
      }
      setResponse(data as CouncilResponse);
    } catch (err) {
      const msg =
        err instanceof DOMException && err.name === "AbortError"
          ? "Council request timed out after 30s"
          : `Failed to reach council: ${err}`;
      setError(msg);
    } finally {
      clearTimeout(timeoutId);
      setLoading(false);
    }
  }

  return (
    <div className="mt-5 border-t border-gray-800/50 pt-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">
          AI Council
        </span>
        <button
          type="button"
          onClick={askCouncil}
          disabled={loading}
          className="px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide bg-indigo-900/50 text-indigo-200 border border-indigo-700/50 hover:bg-indigo-800/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Consulting…" : response ? "Re-ask" : "Ask the Council"}
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-400 bg-red-950/30 border border-red-900/50 rounded p-2">
          {error}
        </p>
      )}

      {response && (
        <div className="space-y-3">
          <p className="text-gray-300 text-xs leading-relaxed whitespace-pre-wrap border-l-2 border-indigo-700/60 pl-3">
            {response.answer}
          </p>

          {response.sources?.length > 0 && (
            <div>
              <div className="text-[9px] uppercase tracking-wider text-gray-600 mb-1">
                Sources · {response.llm_provider}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {response.sources.slice(0, 5).map((s, i) => (
                  <span
                    key={`${s.source_file}-${s.chunk_index}-${i}`}
                    title={s.text_preview}
                    className="px-1.5 py-0.5 rounded bg-gray-900/60 border border-gray-800 text-[9px] text-gray-400"
                  >
                    {s.source_file.split("/").pop()} · {s.rerank_score.toFixed(2)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {response.context_empty && (
            <p className="text-[10px] text-yellow-500/70 italic">
              No matching context in the RAG corpus — answer is from the LLM's general knowledge.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
