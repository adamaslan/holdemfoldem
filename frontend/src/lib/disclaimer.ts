export const DISCLAIMER_VERSION = "1.0";
export const DISCLAIMER_LAST_UPDATED = "2026-05-16";

export const DISCLAIMER_TEXT = `Not investment advice. Hold Em or Fold Em is an educational and analytical tool that aggregates publicly available market data and applies rule-based technical analysis. It is NOT a registered investment adviser, broker-dealer, financial planner, or fiduciary, and its output is NOT personalized investment advice, a recommendation to buy or sell any security, or a solicitation of any transaction.

Verdicts are signals, not decisions. "HOLD EM," "FOLD EM," and "NEUTRAL" are shorthand labels derived from technical indicators (RSI, MACD, ADX, ATR, Fibonacci levels, options Greeks). They do not consider your financial situation, risk tolerance, tax circumstances, time horizon, liquidity needs, or any other personal factor. Two users seeing the same verdict may have completely different correct actions.

Data may be incomplete, delayed, or wrong. Market data is supplied by third parties (currently yfinance and underlying exchanges). It may be delayed by up to 20 minutes, missing for thinly-traded securities, incorrect during corporate actions, or unavailable during outages. Cached results may be up to one hour old.

Options carry uncapped risk. Selling uncovered options (naked calls/puts), credit spreads, and certain combination strategies can result in losses many times larger than the premium received, up to and including total loss of capital and assignment obligations exceeding the value of your account. The "Probability of Profit" shown is a rough uniform-distribution estimate, NOT a Black-Scholes or Monte Carlo result, and systematically overestimates PoP for out-of-the-money strategies. Options are not suitable for all investors. Read the OCC's Characteristics and Risks of Standardized Options before trading.

Past performance does not predict future results. Backtests, technical patterns, and historical price action have no proven predictive power on any specific future trade.

You are solely responsible for your trading decisions, for verifying any output against authoritative sources, for understanding the tax implications of your trades, and for compliance with all applicable laws and your broker's terms.

No warranty. This tool is provided "AS IS" without warranty of any kind, express or implied, including but not limited to merchantability, fitness for a particular purpose, accuracy, and non-infringement. To the maximum extent permitted by law, the operators of this tool disclaim all liability for any direct, indirect, incidental, consequential, special, or punitive damages arising from your use of or inability to use the tool.

Jurisdiction. This tool is operated from the United States. If you access it from a jurisdiction where the provision of such information is restricted, you are responsible for compliance with local law.

By using this tool you acknowledge that you have read, understood, and agreed to the terms above.

Last updated: ${DISCLAIMER_LAST_UPDATED} — version ${DISCLAIMER_VERSION}`;

// Simple djb2 hash — no crypto dependency needed for this non-security use case
function djb2(str: string): string {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) ^ str.charCodeAt(i);
    hash = hash >>> 0; // keep unsigned 32-bit
  }
  return hash.toString(16).padStart(8, "0").slice(0, 12);
}

export const DISCLAIMER_HASH = djb2(DISCLAIMER_TEXT + DISCLAIMER_VERSION);
export const DISCLAIMER_STORAGE_KEY = "hofem.disclaimer.ack";

export function hasAcknowledged(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(DISCLAIMER_STORAGE_KEY) === DISCLAIMER_HASH;
}

export function markAcknowledged(): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(DISCLAIMER_STORAGE_KEY, DISCLAIMER_HASH);
}
