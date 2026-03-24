"use client";
import { useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
interface FibLevel { name: string; price: number; distance_pct: number; strength: string; type: string }
interface Signal    { signal: string; desc: string; strength: string; ai_score?: number }
interface OptionsLeg {
  role: string;
  strike: number | null;
  expiry: string | null;
  premium: number | null;       // per-share premium for this leg
}
interface PayoffPoint { price: number; pnl: number }
interface Verdict {
  symbol: string; asset_type: string; verdict: "HOLD EM" | "FOLD EM" | "NEUTRAL";
  confidence: number; price: number; bias: string; risk_level: string; cached: boolean;
  bullish_count: number; bearish_count: number; avg_score: number; top_signals: Signal[];
  rsi: number | null; macd: number | null; adx: number | null; atr: number | null;
  volatility_regime: string; volume_spike: string | null;
  suppressions: { code: string; label: string }[];
  trade_timeframe: string | null; entry: number | null; stop: number | null;
  target: number | null; risk_reward: number | null; stop_pct: number | null;
  upside_pct: number | null; vehicle: string | null; vehicle_notes: string | null;
  primary_signal: string | null; supporting_signals: string[];
  position_qty: number | null; position_entry: number | null; position_side: string;
  position_pnl_pct: number | null; position_pnl_dollar: number | null;
  position_vs_stop: string | null; position_vs_target: string | null;
  fib_levels: FibLevel[]; fib_confluence_zones: { price: number; strength: string; signal_count: number; confluence_score: number }[];
  nearest_fib_support: number | null; nearest_fib_resistance: number | null;
  options_greeks: { iv: number | null; pcr: number | null; delta_atm: number | null; theta_atm: number | null; vega_atm: number | null } | null;
  options_strategy: string | null;
  options_legs: OptionsLeg[] | null;
  dte: number | null;
  net_premium: number | null;        // net credit (+) or debit (-)
  max_profit: number | null;
  max_loss: number | null;
  breakeven_prices: number[] | null;
  spread_width: number | null;       // for spreads: distance between strikes
  pop: number | null;                // probability of profit estimate
  strategy_note: string | null;
  payoff_curve: PayoffPoint[] | null;
  summary: string; data_timestamp: string | null;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const PERIODS = [
  { v: "1mo", l: "1M" }, { v: "3mo", l: "3M" }, { v: "6mo", l: "6M" },
  { v: "1y", l: "1Y" }, { v: "2y", l: "2Y" },
] as const;

const STRATEGIES = [
  { v: "long_call",          l: "Long Call",          e: "📈", bias: "bull",
    legs: ["long_call"],
    premiumLabel: "Premium Paid",    premiumSign: -1, legCount: 1 },
  { v: "long_put",           l: "Long Put",           e: "📉", bias: "bear",
    legs: ["long_put"],
    premiumLabel: "Premium Paid",    premiumSign: -1, legCount: 1 },
  { v: "covered_call",       l: "Covered Call",       e: "🛡️", bias: "neut",
    legs: ["long_stock", "short_call"],
    premiumLabel: "Premium Received", premiumSign: 1, legCount: 1 },
  { v: "cash_secured_put",   l: "Cash-Secured Put",   e: "💵", bias: "neut",
    legs: ["short_put"],
    premiumLabel: "Premium Received", premiumSign: 1, legCount: 1 },
  { v: "bull_call_spread",   l: "Bull Call Spread",   e: "🐂", bias: "bull",
    legs: ["long_call", "short_call"],
    premiumLabel: "Net Debit Paid",   premiumSign: -1, legCount: 2 },
  { v: "bear_put_spread",    l: "Bear Put Spread",    e: "🐻", bias: "bear",
    legs: ["long_put", "short_put"],
    premiumLabel: "Net Debit Paid",   premiumSign: -1, legCount: 2 },
  { v: "call_credit_spread", l: "Call Credit Spread", e: "⬇️", bias: "bear",
    legs: ["short_call", "long_call"],
    premiumLabel: "Net Credit Received", premiumSign: 1, legCount: 2 },
  { v: "put_credit_spread",  l: "Put Credit Spread",  e: "⬆️", bias: "bull",
    legs: ["short_put", "long_put"],
    premiumLabel: "Net Credit Received", premiumSign: 1, legCount: 2 },
  { v: "iron_condor",        l: "Iron Condor",        e: "🦅", bias: "neut",
    legs: ["long_put", "short_put", "short_call", "long_call"],
    premiumLabel: "Net Credit Received", premiumSign: 1, legCount: 4 },
  { v: "iron_butterfly",     l: "Iron Butterfly",     e: "🦋", bias: "neut",
    legs: ["long_put", "short_put_atm", "short_call_atm", "long_call"],
    premiumLabel: "Net Credit Received", premiumSign: 1, legCount: 4 },
  { v: "straddle",           l: "Long Straddle",      e: "💥", bias: "vola",
    legs: ["long_call", "long_put"],
    premiumLabel: "Total Debit Paid", premiumSign: -1, legCount: 2 },
  { v: "strangle",           l: "Long Strangle",      e: "🌪️", bias: "vola",
    legs: ["long_put_otm", "long_call_otm"],
    premiumLabel: "Total Debit Paid", premiumSign: -1, legCount: 2 },
  { v: "calendar_spread",    l: "Calendar Spread",    e: "📅", bias: "neut",
    legs: ["short_near", "long_far"],
    premiumLabel: "Net Debit Paid",   premiumSign: -1, legCount: 2 },
  { v: "diagonal_spread",    l: "Diagonal Spread",    e: "↗️", bias: "bull",
    legs: ["long_far_itm", "short_near_otm"],
    premiumLabel: "Net Debit Paid",   premiumSign: -1, legCount: 2 },
] as const;

type StrategyV = typeof STRATEGIES[number]["v"];

const BIAS_COLOR: Record<string, string> = {
  bull: "border-green-700/60 text-green-300",
  bear: "border-red-700/60 text-red-300",
  neut: "border-yellow-700/60 text-yellow-300",
  vola: "border-orange-700/60 text-orange-300",
};

const DTE_PRESETS = [
  { v: 7, l: "7d" }, { v: 14, l: "14d" }, { v: 21, l: "21d" },
  { v: 30, l: "30d" }, { v: 45, l: "45d" }, { v: 60, l: "60d" },
  { v: 90, l: "90d" },
];

// ── Leg label maps ─────────────────────────────────────────────────────────────
const LEG_LABELS: Record<StrategyV, string[]> = {
  long_call:          ["Strike"],
  long_put:           ["Strike"],
  covered_call:       ["Stock Price", "Short Call Strike"],
  cash_secured_put:   ["Short Put Strike"],
  bull_call_spread:   ["Long Call Strike (lower)", "Short Call Strike (upper)"],
  bear_put_spread:    ["Long Put Strike (upper)", "Short Put Strike (lower)"],
  call_credit_spread: ["Short Call Strike (lower)", "Long Call Strike (upper)"],
  put_credit_spread:  ["Short Put Strike (upper)", "Long Put Strike (lower)"],
  iron_condor:        ["Long Put (wing)", "Short Put", "Short Call", "Long Call (wing)"],
  iron_butterfly:     ["Long Put (wing)", "ATM Short Strike", "ATM Short Strike", "Long Call (wing)"],
  straddle:           ["Call Strike (ATM)", "Put Strike (ATM)"],
  strangle:           ["Put Strike (OTM)", "Call Strike (OTM)"],
  calendar_spread:    ["Near-term Sell Strike", "Far-term Buy Strike"],
  diagonal_spread:    ["Far-term Buy Strike (ITM)", "Near-term Sell Strike (OTM)"],
};

// ── Mini components ───────────────────────────────────────────────────────────
function Bar({ v, color }: { v: number; color: string }) {
  return (
    <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
      <div className={`h-1.5 rounded-full transition-all duration-700 ${color}`} style={{ width: `${Math.min(v, 100)}%` }} />
    </div>
  );
}

function Chip({ label, value, color = "text-white", sub }: { label: string; value: string | number | null; color?: string; sub?: string }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="rounded-xl bg-gray-900/70 border border-gray-800 p-3 text-center">
      <div className="text-gray-600 text-[9px] uppercase tracking-widest">{label}</div>
      <div className={`text-sm font-bold mt-0.5 ${color}`}>{value}</div>
      {sub && <div className="text-gray-700 text-[9px] mt-0.5">{sub}</div>}
    </div>
  );
}

function Row({ label, value, valueClass = "text-gray-300" }: { label: string; value: string | null | undefined; valueClass?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-gray-800/60">
      <span className="text-gray-600 text-xs">{label}</span>
      <span className={`text-xs font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-gray-600 text-[9px] uppercase tracking-widest mt-5 mb-2 font-bold">{children}</div>;
}

function PillBtn({ active, onClick, children, activeClass = "bg-green-600 text-white" }: {
  active: boolean; onClick: () => void; children: React.ReactNode; activeClass?: string;
}) {
  return (
    <button type="button" onClick={onClick}
      className={`flex-1 rounded-lg py-2 text-xs font-bold transition-all ${active ? activeClass : "bg-gray-800 text-gray-500 hover:bg-gray-700"}`}>
      {children}
    </button>
  );
}

function NumInput({ label, value, onChange, placeholder, step = "0.01", prefix }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; step?: string; prefix?: string;
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="text-gray-600 text-[9px] uppercase tracking-widest mb-1">{label}</div>
      <div className="relative">
        {prefix && <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 text-xs">{prefix}</span>}
        <input
          type="number" step={step} min="0" placeholder={placeholder ?? "—"}
          value={value} onChange={(e) => onChange(e.target.value)}
          className={`w-full rounded-lg border border-gray-700 bg-gray-900 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-purple-500 ${prefix ? "pl-5 pr-2" : "px-2"}`}
        />
      </div>
    </div>
  );
}

// Mini payoff chart (SVG sparkline)
function PayoffChart({ points, currentPrice }: { points: PayoffPoint[]; currentPrice: number }) {
  if (!points || points.length < 2) return null;
  const W = 400; const H = 80;
  const prices = points.map((p) => p.price);
  const pnls   = points.map((p) => p.pnl);
  const minP = Math.min(...prices); const maxP = Math.max(...prices);
  const minPnl = Math.min(...pnls); const maxPnl = Math.max(...pnls);
  const rangeP   = maxP - minP || 1;
  const rangePnl = maxPnl - minPnl || 1;
  const toX = (p: number) => ((p - minP) / rangeP) * W;
  const toY = (pnl: number) => H - ((pnl - minPnl) / rangePnl) * H;
  const zeroY = toY(0);
  const pathD = points.map((pt, i) => `${i === 0 ? "M" : "L"}${toX(pt.price).toFixed(1)},${toY(pt.pnl).toFixed(1)}`).join(" ");
  const curX  = toX(currentPrice);

  return (
    <div className="mt-2 rounded-lg bg-gray-900/60 border border-gray-800 p-2">
      <div className="text-gray-600 text-[9px] uppercase tracking-widest mb-1">Payoff at Expiry</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-16" preserveAspectRatio="none">
        {/* Zero line */}
        <line x1="0" y1={zeroY} x2={W} y2={zeroY} stroke="#374151" strokeWidth="1" strokeDasharray="4,3" />
        {/* Profit fill */}
        <path d={`${pathD} L${toX(prices[prices.length-1]).toFixed(1)},${zeroY} L${toX(prices[0]).toFixed(1)},${zeroY} Z`}
          fill="rgba(34,197,94,0.08)" />
        {/* Loss fill */}
        <path d={`M${toX(prices[0]).toFixed(1)},${zeroY} ${pathD} L${toX(prices[prices.length-1]).toFixed(1)},${zeroY} Z`}
          fill="rgba(239,68,68,0.08)" />
        {/* Payoff line */}
        <path d={pathD} fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinejoin="round" />
        {/* Current price marker */}
        <line x1={curX} y1="0" x2={curX} y2={H} stroke="#60a5fa" strokeWidth="1" strokeDasharray="3,2" />
        <circle cx={curX} cy={toY(points.find((p) => Math.abs(p.price - currentPrice) < rangeP / points.length * 1.5)?.pnl ?? 0)} r="3" fill="#60a5fa" />
      </svg>
      <div className="flex justify-between text-[9px] text-gray-700 font-mono mt-0.5">
        <span>${minP.toFixed(0)}</span><span className="text-blue-600">↑ Now ${currentPrice.toFixed(2)}</span><span>${maxP.toFixed(0)}</span>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function Home() {
  const [symbol, setSymbol]           = useState("");
  const [period, setPeriod]           = useState("3mo");
  const [strategy, setStrategy]       = useState<StrategyV | null>(null);
  const [showOptions, setShowOptions] = useState(false);

  // DTE
  const [dte, setDte]         = useState<number | null>(null);
  const [customDte, setCustomDte] = useState("");

  // Strikes — up to 4 legs
  const [strikes, setStrikes] = useState(["", "", "", ""]);
  const setStrike = (i: number, v: string) => setStrikes((prev) => prev.map((s, j) => j === i ? v : s));

  // Net premium: single field for the net credit/debit of the whole position
  const [netPremium, setNetPremium] = useState("");

  // Underlying price range for spread analysis (optional — used for payoff accuracy)
  const [spotLow, setSpotLow]   = useState("");   // lower price anchor for payoff chart
  const [spotHigh, setSpotHigh] = useState("");   // upper price anchor

  // Existing position
  const [posEntry, setPosEntry] = useState("");
  const [posQty, setPosQty]     = useState("");
  const [posSide, setPosSide]   = useState("long");
  const [showPos, setShowPos]   = useState(false);

  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const effectiveDte = customDte ? parseInt(customDte) : dte;
  const selectedStrat = STRATEGIES.find((s) => s.v === strategy);
  const legCount = selectedStrat?.legCount ?? 0;
  const legLabels = strategy ? (LEG_LABELS[strategy] ?? []) : [];

  function resetOptions() {
    setStrategy(null); setStrikes(["", "", "", ""]); setNetPremium("");
    setSpotLow(""); setSpotHigh(""); setDte(null); setCustomDte("");
  }

  function buildLegsPayload() {
    if (!strategy || !selectedStrat) return null;
    return selectedStrat.legs.map((role, i) => ({
      role,
      strike: strikes[i] ? parseFloat(strikes[i]) : null,
      expiry: effectiveDte ? `${effectiveDte}dte` : null,
      premium: null, // individual leg premiums not collected; net_premium covers it
    }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!symbol.trim()) return;
    setLoading(true); setError(null); setVerdict(null);
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol:           symbol.toUpperCase(),
          period,
          asset_type:       strategy ? "options" : "stock",
          options_strategy: strategy ?? null,
          options_legs:     buildLegsPayload(),
          dte:              effectiveDte ?? null,
          net_premium:      netPremium ? parseFloat(netPremium) : null,
          premium_sign:     selectedStrat?.premiumSign ?? null, // +1 credit, -1 debit
          spot_low:         spotLow  ? parseFloat(spotLow)  : null,
          spot_high:        spotHigh ? parseFloat(spotHigh) : null,
          position_entry:   posEntry ? parseFloat(posEntry) : null,
          position_qty:     posQty   ? parseFloat(posQty)   : null,
          position_side:    posSide,
        }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        const msg = e.detail ?? e.error ?? e.message ?? `HTTP ${res.status}`;
        throw new Error(msg);
      }
      setVerdict(await res.json());
    } catch (e) { setError(String(e).replace(/^Error:\s*/, "")); } finally { setLoading(false); }
  }

  const vc = verdict?.verdict === "HOLD EM"
    ? { text: "text-green-400", border: "border-green-500/30", bg: "bg-green-950/10" }
    : verdict?.verdict === "FOLD EM"
    ? { text: "text-red-400", border: "border-red-500/30", bg: "bg-red-950/10" }
    : { text: "text-yellow-400", border: "border-yellow-500/30", bg: "bg-yellow-950/10" };

  const confColor = (verdict?.confidence ?? 0) >= 75 ? "bg-green-500" : (verdict?.confidence ?? 0) >= 60 ? "bg-yellow-500" : "bg-red-500";
  const pnlColor  = (verdict?.position_pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400";
  const rsiColor  = (verdict?.rsi ?? 50) < 30 ? "text-green-300" : (verdict?.rsi ?? 50) > 70 ? "text-red-300" : "text-white";

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center px-4 py-10 font-sans">

      {/* Header */}
      <div className="mb-8 text-center">
        <h1 className="text-5xl font-black tracking-tighter">
          <span className="text-green-400">Hold</span>
          <span className="text-gray-600 mx-2 text-4xl">em or</span>
          <span className="text-red-400">Fold</span>
        </h1>
        <p className="text-gray-600 text-sm mt-1">Live signals · Fibonacci · Options payoff · Position P&amp;L</p>
      </div>

      {/* Form */}
      <form onSubmit={submit} className="w-full max-w-lg flex flex-col gap-3">

        {/* Ticker */}
        <div className="relative">
          <input type="text" autoFocus
            placeholder="AAPL · SPY · QQQ · BTC-USD"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-4 text-2xl font-black uppercase tracking-widest focus:outline-none focus:ring-2 focus:ring-green-500 placeholder:text-gray-700 placeholder:font-normal placeholder:text-sm placeholder:tracking-normal placeholder:normal-case"
          />
          {symbol && (
            <button type="button" onClick={() => setSymbol("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 text-lg">×</button>
          )}
        </div>

        {/* Options toggle */}
        <button type="button"
          onClick={() => { setShowOptions((x) => !x); if (showOptions) resetOptions(); }}
          className={`rounded-xl border py-2.5 text-sm font-bold transition-all ${showOptions ? "border-purple-500 bg-purple-900/20 text-purple-300" : "border-gray-700 bg-gray-900/50 text-gray-500 hover:text-gray-300"}`}>
          {showOptions ? "⚡ Options Mode" : "⚡ Add Options Strategy"}
        </button>

        {/* Strategy panel */}
        {showOptions && (
          <div className="rounded-xl border border-purple-800/40 bg-purple-950/20 p-3 flex flex-col gap-3">

            {/* Strategy picker */}
            <div>
              <div className="text-purple-400 text-[9px] uppercase tracking-widest mb-1.5">Strategy</div>
              <div className="grid grid-cols-2 gap-1.5">
                {STRATEGIES.map((s) => {
                  const sel = strategy === s.v;
                  return (
                    <button key={s.v} type="button"
                      onClick={() => { setStrategy(sel ? null : s.v); setStrikes(["", "", "", ""]); setNetPremium(""); }}
                      className={`text-left rounded-lg border px-2.5 py-2 text-xs font-bold transition-all ${sel ? "bg-purple-900/60 border-purple-500 text-purple-200" : `bg-gray-900/40 ${BIAS_COLOR[s.bias]}`}`}>
                      {s.e} {s.l}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* DTE */}
            <div>
              <div className="text-gray-500 text-[9px] uppercase tracking-widest mb-1.5">Days to Expiration (DTE)</div>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {DTE_PRESETS.map(({ v, l }) => (
                  <button key={v} type="button"
                    onClick={() => { setDte(dte === v ? null : v); setCustomDte(""); }}
                    className={`rounded-lg px-3 py-1 text-xs font-bold transition-all ${dte === v && !customDte ? "bg-purple-700 text-white" : "bg-gray-800 text-gray-500 hover:bg-gray-700"}`}>
                    {l}
                  </button>
                ))}
              </div>
              <input type="number" min="1" max="730" step="1" placeholder="Custom DTE (e.g. 25)"
                value={customDte}
                onChange={(e) => { setCustomDte(e.target.value); setDte(null); }}
                className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-purple-500 placeholder:text-gray-600" />
              {effectiveDte && <div className="text-purple-400 text-[10px] mt-1">{effectiveDte} days to expiration</div>}
            </div>

            {/* Strikes */}
            {strategy && legCount > 0 && (
              <div>
                <div className="text-gray-500 text-[9px] uppercase tracking-widest mb-1.5">
                  Strike Prices <span className="text-gray-700 normal-case">(optional but needed for payoff math)</span>
                </div>
                <div className={`grid gap-2 ${legCount === 1 ? "grid-cols-1" : "grid-cols-2"}`}>
                  {legLabels.slice(0, legCount).map((label, i) => (
                    <NumInput key={i} label={label} value={strikes[i]} onChange={(v) => setStrike(i, v)} prefix="$" step="0.5" />
                  ))}
                </div>
              </div>
            )}

            {/* Net premium */}
            {strategy && (
              <div className="grid grid-cols-2 gap-2">
                <NumInput
                  label={selectedStrat?.premiumLabel ?? "Net Premium"}
                  value={netPremium}
                  onChange={setNetPremium}
                  placeholder="e.g. 1.25"
                  prefix="$"
                  step="0.01"
                />
                {/* Spot price range for payoff chart accuracy */}
                <div className="flex flex-col gap-1.5">
                  <div className="text-gray-500 text-[9px] uppercase tracking-widest">Price Range (chart)</div>
                  <div className="flex gap-1">
                    <input type="number" step="0.5" min="0" placeholder="Low"
                      value={spotLow} onChange={(e) => setSpotLow(e.target.value)}
                      className="flex-1 min-w-0 rounded-lg border border-gray-700 bg-gray-900 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500" />
                    <input type="number" step="0.5" min="0" placeholder="High"
                      value={spotHigh} onChange={(e) => setSpotHigh(e.target.value)}
                      className="flex-1 min-w-0 rounded-lg border border-gray-700 bg-gray-900 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-purple-500" />
                  </div>
                </div>
              </div>
            )}

            {/* Premium sign hint */}
            {selectedStrat && netPremium && (
              <div className={`text-[10px] px-3 py-1.5 rounded-lg border ${selectedStrat.premiumSign === 1
                ? "bg-green-950/30 border-green-800/40 text-green-400"
                : "bg-red-950/30 border-red-800/40 text-red-400"}`}>
                {selectedStrat.premiumSign === 1
                  ? `+$${netPremium}/share credit received · max loss = spread width − credit`
                  : `-$${netPremium}/share debit paid · max loss = debit`}
              </div>
            )}
          </div>
        )}

        {/* Period */}
        <div className="flex gap-2">
          {PERIODS.map(({ v, l }) => (
            <PillBtn key={v} active={period === v} onClick={() => setPeriod(v)} activeClass="bg-blue-700 text-white">{l}</PillBtn>
          ))}
        </div>

        {/* Position toggle */}
        <button type="button" onClick={() => setShowPos((x) => !x)}
          className="text-gray-600 hover:text-gray-400 text-xs text-left flex items-center gap-1 transition-colors">
          <span className={`transition-transform ${showPos ? "rotate-90" : ""}`}>▶</span>
          {showPos ? "Hide" : "Add"} existing position (optional — for P&amp;L tracking)
        </button>

        {showPos && (
          <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4 flex flex-col gap-3">
            <div className="flex gap-2">
              <div className="flex-1">
                <div className="text-gray-600 text-[9px] uppercase tracking-widest mb-1">Cost Basis / Share</div>
                <input type="number" step="0.01" min="0" placeholder="e.g. 182.50"
                  value={posEntry} onChange={(e) => setPosEntry(e.target.value)}
                  className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-500" />
              </div>
              <div className="flex-1">
                <div className="text-gray-600 text-[9px] uppercase tracking-widest mb-1">Shares / Contracts</div>
                <input type="number" step="1" min="0" placeholder="e.g. 100"
                  value={posQty} onChange={(e) => setPosQty(e.target.value)}
                  className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-500" />
              </div>
            </div>
            <div className="flex gap-2">
              <PillBtn active={posSide === "long"}  onClick={() => setPosSide("long")}  activeClass="bg-green-700 text-white">Long</PillBtn>
              <PillBtn active={posSide === "short"} onClick={() => setPosSide("short")} activeClass="bg-red-700 text-white">Short</PillBtn>
            </div>
          </div>
        )}

        <button type="submit" disabled={loading || !symbol.trim()}
          className="rounded-xl bg-gradient-to-r from-green-600 to-emerald-500 hover:from-green-500 hover:to-emerald-400 disabled:opacity-40 py-4 text-lg font-black tracking-wide transition-all shadow-lg shadow-green-900/30">
          {loading
            ? <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                Analyzing {symbol}…
              </span>
            : "Analyze"}
        </button>
      </form>

      {/* Error */}
      {error && (() => {
        const e = error.toLowerCase();
        const isRateLimit   = e.includes("rate") || e.includes("too many");
        const isUnreachable = e.includes("unreachable") || e.includes("econnrefused");
        const isUnavailable = e.includes("503") || e.includes("service unavailable");
        const title = isRateLimit   ? "⏳ Rate Limited"
                    : isUnreachable ? "🔌 Backend Unreachable"
                    : isUnavailable ? "🚫 Service Unavailable"
                    : "❌ Analysis Failed";
        return (
          <div className="mt-6 w-full max-w-lg rounded-xl border border-red-500/40 bg-red-950/30 p-4 text-sm space-y-1">
            <div className="text-red-300 font-semibold">{title}</div>
            <div className="text-red-400/80">{error}</div>
            {isRateLimit   && <div className="text-red-500/60 text-xs mt-1">Yahoo Finance rate-limits heavy usage. Wait 30–60 seconds and try again.</div>}
            {isUnreachable && <div className="text-red-500/60 text-xs mt-1">Start the backend: <code className="bg-red-950 px-1 rounded">python backend/main.py</code></div>}
          </div>
        );
      })()}

      {/* Result card */}
      {verdict && (
        <div className={`mt-8 w-full max-w-lg rounded-2xl border shadow-2xl ${vc.border} ${vc.bg}`}>
          <div className="p-6">

            {/* Header */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <div className="text-3xl font-black">{verdict.symbol}</div>
                <div className="text-gray-500 text-xs mt-0.5">
                  <span className="font-mono text-gray-400">${verdict.price.toFixed(2)}</span>
                  {" · "}{verdict.asset_type.toUpperCase()}
                  {verdict.dte && <span className="ml-2 text-purple-400">{verdict.dte}d DTE</span>}
                  {verdict.data_timestamp && <span className="ml-2 text-gray-700">{new Date(verdict.data_timestamp).toLocaleDateString()}</span>}
                  {verdict.cached && <span className="ml-2 text-indigo-600">· cached</span>}
                </div>
              </div>
              <div className="text-right flex flex-col items-end gap-1">
                <span className={`px-2 py-0.5 rounded-full text-[9px] font-black border uppercase tracking-wide ${
                  verdict.risk_level === "low"    ? "bg-green-900/50 text-green-300 border-green-700/50" :
                  verdict.risk_level === "medium" ? "bg-yellow-900/50 text-yellow-300 border-yellow-700/50" :
                  verdict.risk_level === "high"   ? "bg-orange-900/50 text-orange-300 border-orange-700/50" :
                  "bg-red-900/50 text-red-300 border-red-700/50"}`}>
                  {verdict.risk_level} risk
                </span>
                <span className="text-gray-700 text-[9px] uppercase">{verdict.volatility_regime} vol</span>
              </div>
            </div>

            {/* Verdict */}
            <div className="text-center mb-5">
              <div className={`text-6xl font-black tracking-tight ${vc.text}`}>{verdict.verdict}</div>
              <div className="text-gray-500 text-sm mt-1 capitalize">{verdict.bias} bias · {verdict.trade_timeframe ?? "—"}</div>
            </div>

            {/* Confidence */}
            <div className="mb-5">
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>Conviction</span><span className="font-bold text-white">{verdict.confidence}%</span>
              </div>
              <Bar v={verdict.confidence} color={confColor} />
            </div>

            {/* Signal counts */}
            <div className="grid grid-cols-3 gap-2 mb-2">
              <Chip label="Bullish" value={verdict.bullish_count} color="text-green-400" sub="signals" />
              <Chip label="Avg Score" value={`${verdict.avg_score.toFixed(0)}/100`}
                color={verdict.avg_score >= 65 ? "text-green-400" : verdict.avg_score >= 50 ? "text-yellow-400" : "text-red-400"} />
              <Chip label="Bearish" value={verdict.bearish_count} color="text-red-400" sub="signals" />
            </div>

            {/* Market indicators */}
            <SectionLabel>Market Indicators</SectionLabel>
            <div className="grid grid-cols-4 gap-2 mb-1">
              <Chip label="RSI"  value={verdict.rsi?.toFixed(1) ?? null} color={rsiColor} />
              <Chip label="ADX"  value={verdict.adx?.toFixed(1) ?? null} color={(verdict.adx ?? 0) > 25 ? "text-green-300" : "text-yellow-300"} />
              <Chip label="ATR"  value={verdict.atr ? `$${verdict.atr.toFixed(2)}` : null} />
              <Chip label="MACD" value={verdict.macd?.toFixed(3) ?? null} color={(verdict.macd ?? 0) > 0 ? "text-green-300" : "text-red-300"} />
            </div>
            {verdict.volume_spike && (
              <div className="text-xs text-yellow-300 bg-yellow-900/20 border border-yellow-800/40 rounded-lg px-3 py-1.5 mt-2">
                Volume spike: {verdict.volume_spike}
              </div>
            )}

            {/* ── OPTIONS STRATEGY BLOCK ── */}
            {verdict.options_strategy && (
              <>
                <SectionLabel>Options Position</SectionLabel>
                <div className="rounded-xl bg-purple-950/30 border border-purple-800/30 p-3 flex flex-col gap-2.5">

                  {/* Strategy header */}
                  <div className="flex items-center justify-between">
                    <span className="text-purple-200 font-bold text-sm">
                      {STRATEGIES.find((s) => s.v === verdict.options_strategy)?.e}{" "}
                      {STRATEGIES.find((s) => s.v === verdict.options_strategy)?.l}
                    </span>
                    <div className="flex items-center gap-2">
                      {verdict.dte && <span className="text-purple-400 text-xs font-mono">{verdict.dte}d DTE</span>}
                      {verdict.pop !== null && (
                        <span className={`text-[9px] font-black px-2 py-0.5 rounded-full border ${
                          (verdict.pop ?? 0) >= 65 ? "text-green-300 border-green-700/50 bg-green-900/30" :
                          (verdict.pop ?? 0) >= 50 ? "text-yellow-300 border-yellow-700/50 bg-yellow-900/30" :
                          "text-red-300 border-red-700/50 bg-red-900/30"}`}>
                          {verdict.pop?.toFixed(0)}% PoP
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Strategy note */}
                  {verdict.strategy_note && (
                    <div className="text-gray-500 text-[11px] leading-relaxed">{verdict.strategy_note}</div>
                  )}

                  {/* Legs table */}
                  {verdict.options_legs && verdict.options_legs.length > 0 && (
                    <div className="flex flex-col gap-1">
                      <div className="text-gray-600 text-[9px] uppercase tracking-widest">Legs</div>
                      {verdict.options_legs.map((leg, i) => (
                        <div key={i} className="flex justify-between items-center text-xs bg-gray-900/50 rounded-lg px-3 py-1.5">
                          <span className="text-gray-400 capitalize">{leg.role.replace(/_/g, " ")}</span>
                          <span className="flex items-center gap-3">
                            {leg.expiry && <span className="text-purple-400 text-[10px]">{leg.expiry}</span>}
                            {leg.strike != null && <span className="font-mono text-white">${leg.strike.toFixed(2)}</span>}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* P&L metrics: net premium, max profit, max loss, width, breakevens */}
                  <div className="grid grid-cols-2 gap-2">
                    {verdict.net_premium !== null && (
                      <div className={`rounded-lg border p-2 text-center ${verdict.net_premium >= 0
                        ? "bg-green-950/40 border-green-800/40" : "bg-red-950/40 border-red-800/40"}`}>
                        <div className="text-gray-600 text-[9px] uppercase tracking-widest">
                          {verdict.net_premium >= 0 ? "Credit Received" : "Debit Paid"}
                        </div>
                        <div className={`font-bold text-sm ${verdict.net_premium >= 0 ? "text-green-300" : "text-red-300"}`}>
                          {verdict.net_premium >= 0 ? "+" : ""}${Math.abs(verdict.net_premium).toFixed(2)}
                          <span className="text-gray-600 text-[9px] ml-1 font-normal">/share</span>
                        </div>
                        <div className="text-gray-700 text-[9px]">
                          ${(Math.abs(verdict.net_premium) * 100).toFixed(0)}/contract
                        </div>
                      </div>
                    )}
                    {verdict.spread_width !== null && (
                      <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-2 text-center">
                        <div className="text-gray-600 text-[9px] uppercase tracking-widest">Spread Width</div>
                        <div className="font-bold text-sm text-gray-200">${verdict.spread_width.toFixed(2)}</div>
                        <div className="text-gray-700 text-[9px]">${(verdict.spread_width * 100).toFixed(0)}/contract</div>
                      </div>
                    )}
                    {verdict.max_profit !== null && (
                      <div className="rounded-lg border border-green-800/40 bg-green-950/30 p-2 text-center">
                        <div className="text-gray-600 text-[9px] uppercase tracking-widest">Max Profit</div>
                        <div className="font-bold text-sm text-green-300">
                          {verdict.max_profit >= 1e9 ? "Unlimited" : `$${verdict.max_profit.toFixed(2)}`}
                        </div>
                        {verdict.max_profit < 1e9 && (
                          <div className="text-gray-700 text-[9px]">${(verdict.max_profit * 100).toFixed(0)}/contract</div>
                        )}
                      </div>
                    )}
                    {verdict.max_loss !== null && (
                      <div className="rounded-lg border border-red-800/40 bg-red-950/30 p-2 text-center">
                        <div className="text-gray-600 text-[9px] uppercase tracking-widest">Max Loss</div>
                        <div className="font-bold text-sm text-red-300">
                          {verdict.max_loss >= 1e9 ? "Unlimited" : `$${verdict.max_loss.toFixed(2)}`}
                        </div>
                        {verdict.max_loss < 1e9 && (
                          <div className="text-gray-700 text-[9px]">${(verdict.max_loss * 100).toFixed(0)}/contract</div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* R/R for the option position */}
                  {verdict.max_profit !== null && verdict.max_loss !== null &&
                    verdict.max_profit < 1e9 && verdict.max_loss < 1e9 && verdict.max_loss > 0 && (
                    <div className="flex items-center justify-between text-xs bg-gray-900/50 rounded-lg px-3 py-1.5">
                      <span className="text-gray-500">Options R/R</span>
                      <span className="text-purple-300 font-bold font-mono">
                        {(verdict.max_profit / verdict.max_loss).toFixed(2)}x
                      </span>
                    </div>
                  )}

                  {/* Breakevens */}
                  {verdict.breakeven_prices && verdict.breakeven_prices.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-gray-600 text-[9px] uppercase tracking-widest">BE:</span>
                      {verdict.breakeven_prices.map((be, i) => {
                        const distPct = verdict.price ? ((be - verdict.price) / verdict.price) * 100 : null;
                        return (
                          <span key={i} className="text-xs font-mono text-yellow-300 bg-yellow-950/30 border border-yellow-800/30 rounded px-2 py-0.5">
                            ${be.toFixed(2)}
                            {distPct !== null && (
                              <span className="ml-1 text-[9px] text-gray-500">
                                ({distPct >= 0 ? "+" : ""}{distPct.toFixed(1)}%)
                              </span>
                            )}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Payoff chart */}
                  {verdict.payoff_curve && verdict.payoff_curve.length > 0 && (
                    <PayoffChart points={verdict.payoff_curve} currentPrice={verdict.price} />
                  )}
                </div>
              </>
            )}

            {/* Options greeks */}
            {verdict.options_greeks && (
              <>
                <SectionLabel>Options Chain</SectionLabel>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <Chip label="IV" value={verdict.options_greeks.iv ? `${(verdict.options_greeks.iv * 100).toFixed(1)}%` : null} color="text-purple-300" />
                  <Chip label="P/C Ratio" value={verdict.options_greeks.pcr?.toFixed(2) ?? null}
                    color={(verdict.options_greeks.pcr ?? 1) > 1.2 ? "text-red-300" : (verdict.options_greeks.pcr ?? 1) < 0.8 ? "text-green-300" : "text-yellow-300"} />
                  <Chip label="Delta ATM" value={verdict.options_greeks.delta_atm?.toFixed(3) ?? null} />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Chip label="Theta (decay/day)" value={verdict.options_greeks.theta_atm?.toFixed(4) ?? null} color="text-red-300" />
                  <Chip label="Vega (per 1% IV)"  value={verdict.options_greeks.vega_atm?.toFixed(4) ?? null} color="text-blue-300" />
                </div>
              </>
            )}

            {/* Your position */}
            {verdict.position_entry && (
              <>
                <SectionLabel>Your Position</SectionLabel>
                <div className={`rounded-xl border p-4 mb-1 ${(verdict.position_pnl_pct ?? 0) >= 0 ? "border-green-800/40 bg-green-950/20" : "border-red-800/40 bg-red-950/20"}`}>
                  <div className="grid grid-cols-3 gap-2 mb-3">
                    <Chip label="Entry"   value={`$${verdict.position_entry.toFixed(2)}`} color="text-blue-300" />
                    <Chip label="Current" value={`$${verdict.price.toFixed(2)}`} />
                    <Chip label="P&L %"   value={`${(verdict.position_pnl_pct ?? 0) >= 0 ? "+" : ""}${verdict.position_pnl_pct?.toFixed(2)}%`} color={pnlColor} />
                  </div>
                  {verdict.position_qty && (
                    <div className="grid grid-cols-2 gap-2 mb-3">
                      <Chip label="Qty" value={verdict.position_qty} />
                      <Chip label="Total P&L" value={verdict.position_pnl_dollar != null
                        ? `${(verdict.position_pnl_dollar * (verdict.position_qty ?? 1)) >= 0 ? "+" : ""}$${(verdict.position_pnl_dollar * (verdict.position_qty ?? 1)).toFixed(2)}`
                        : null} color={pnlColor} />
                    </div>
                  )}
                  <div className="flex flex-col gap-0">
                    <Row label="vs Stop"   value={verdict.position_vs_stop}   valueClass={verdict.position_vs_stop?.includes("✗") ? "text-red-400" : "text-green-400"} />
                    <Row label="vs Target" value={verdict.position_vs_target} valueClass={verdict.position_vs_target?.includes("✓") ? "text-green-400" : "text-gray-300"} />
                    <Row label="Side" value={verdict.position_side.toUpperCase()} />
                  </div>
                </div>
              </>
            )}

            {/* Trade plan */}
            {verdict.entry ? (
              <>
                <SectionLabel>Trade Plan ({verdict.trade_timeframe})</SectionLabel>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <Chip label="Entry"  value={`$${verdict.entry.toFixed(2)}`}  color="text-blue-300" />
                  <Chip label="Stop"   value={verdict.stop   ? `$${verdict.stop.toFixed(2)}`   : null} color="text-red-300" />
                  <Chip label="Target" value={verdict.target ? `$${verdict.target.toFixed(2)}` : null} color="text-green-300" />
                </div>
                <div className="grid grid-cols-3 gap-2 mb-2">
                  <Chip label="R/R"     value={verdict.risk_reward ? `${verdict.risk_reward.toFixed(2)}x` : null} color="text-purple-300" />
                  <Chip label="Stop %"  value={verdict.stop_pct    ? `${verdict.stop_pct.toFixed(1)}%`   : null} color="text-red-300" />
                  <Chip label="Upside%" value={verdict.upside_pct  ? `+${verdict.upside_pct.toFixed(1)}%` : null} color="text-green-300" />
                </div>
                {verdict.vehicle && (
                  <div className="text-xs text-gray-500 bg-gray-900/60 border border-gray-800 rounded-lg px-3 py-2">
                    <span className="text-gray-400 font-semibold">{verdict.vehicle.replace("_", " ")}</span>
                    {verdict.vehicle_notes && <span className="ml-2 text-gray-600">{verdict.vehicle_notes}</span>}
                  </div>
                )}
                {verdict.primary_signal && (
                  <div className="text-xs text-gray-600 mt-2">
                    Primary: <span className="text-gray-300 font-semibold">{verdict.primary_signal}</span>
                    {verdict.supporting_signals.length > 0 && (
                      <span className="ml-2">· {verdict.supporting_signals.slice(0, 3).join(" · ")}</span>
                    )}
                  </div>
                )}
              </>
            ) : verdict.suppressions.length > 0 && (
              <>
                <SectionLabel>No Trade Plan — Reasons</SectionLabel>
                <div className="flex flex-col gap-1">
                  {verdict.suppressions.map((s) => (
                    <div key={s.code} className="text-xs text-orange-300 bg-orange-950/20 border border-orange-800/30 rounded-lg px-3 py-1.5">
                      {s.label}
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Fibonacci */}
            {verdict.fib_levels.length > 0 && (
              <>
                <SectionLabel>Fibonacci Key Levels</SectionLabel>
                <div className="grid grid-cols-2 gap-1.5 mb-2">
                  {verdict.nearest_fib_support && <Chip label="Support" value={`$${verdict.nearest_fib_support.toFixed(2)}`} color="text-green-300" />}
                  {verdict.nearest_fib_resistance && <Chip label="Resistance" value={`$${verdict.nearest_fib_resistance.toFixed(2)}`} color="text-red-300" />}
                </div>
                <div className="flex flex-col gap-1">
                  {verdict.fib_levels.map((lv, i) => (
                    <div key={i} className="flex justify-between items-center text-xs border-b border-gray-800/40 py-1">
                      <span className="text-gray-500">{lv.name} <span className="text-gray-700 text-[9px]">{lv.type}</span></span>
                      <span className="flex items-center gap-3">
                        <span className="text-gray-700 text-[9px]">{lv.strength}</span>
                        <span className={`text-[10px] font-mono ${lv.distance_pct < 0 ? "text-green-400" : "text-red-400"}`}>
                          {lv.distance_pct > 0 ? "+" : ""}{lv.distance_pct.toFixed(2)}%
                        </span>
                        <span className="font-mono text-gray-300 w-20 text-right">${lv.price.toFixed(2)}</span>
                      </span>
                    </div>
                  ))}
                </div>
                {verdict.fib_confluence_zones.length > 0 && (
                  <div className="mt-2 flex flex-col gap-1">
                    <div className="text-gray-700 text-[9px] uppercase tracking-widest">Confluence Zones</div>
                    {verdict.fib_confluence_zones.map((z, i) => (
                      <div key={i} className="flex justify-between text-xs bg-indigo-950/20 border border-indigo-900/30 rounded-lg px-3 py-1.5">
                        <span className="text-indigo-300">${z.price.toFixed(2)}</span>
                        <span className="text-gray-600">{z.signal_count} signals · score {z.confluence_score.toFixed(1)}</span>
                        <span className={`font-bold text-[9px] uppercase ${z.strength === "STRONG" ? "text-green-400" : "text-yellow-400"}`}>{z.strength}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* Top signals */}
            <SectionLabel>Top Signals ({verdict.top_signals.length})</SectionLabel>
            <div className="flex flex-col gap-1">
              {verdict.top_signals.map((s, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg bg-gray-900/60 border border-gray-800 px-3 py-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-gray-700 text-xs font-mono w-4 shrink-0">{i + 1}</span>
                    <div className="min-w-0">
                      <span className="font-semibold text-xs">{s.signal}</span>
                      <span className="text-gray-600 text-[10px] ml-2 truncate">{s.desc}</span>
                    </div>
                  </div>
                  <span className={`text-[9px] font-black uppercase tracking-wide shrink-0 ml-2 ${
                    s.strength?.includes("BULLISH") ? "text-green-400" :
                    s.strength?.includes("BEARISH") ? "text-red-400" : "text-yellow-400"}`}>
                    {s.strength?.replace("STRONGLY ", "★ ")}
                  </span>
                </div>
              ))}
            </div>

            {/* Summary */}
            <p className="text-gray-500 text-xs leading-relaxed mt-5 border-l-2 border-gray-800 pl-3">{verdict.summary}</p>
          </div>

          {/* Footer */}
          <div className="border-t border-gray-800/50 px-6 py-3 flex justify-between text-[9px] text-gray-700">
            <span>Hold Em / Fold Em · Fibonacci · Options payoff · Firestore cache</span>
            <span className="uppercase tracking-wide">{verdict.asset_type} · {period}</span>
          </div>
        </div>
      )}
    </main>
  );
}
