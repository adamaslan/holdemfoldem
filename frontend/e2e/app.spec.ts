import { test, expect } from "@playwright/test";

// Pre-seed the disclaimer acknowledgment so the modal never blocks test interactions.
// The hash value is the djb2 fingerprint of the disclaimer text + version computed
// by frontend/src/lib/disclaimer.ts — update this if DISCLAIMER_VERSION changes.
const DISCLAIMER_KEY  = "hofem.disclaimer.ack";
const DISCLAIMER_HASH = "f3205ad7";

test.beforeEach(async ({ page }) => {
  // Seed localStorage before the page renders so the modal never mounts.
  await page.addInitScript(({ key, hash }) => {
    localStorage.setItem(key, hash);
  }, { key: DISCLAIMER_KEY, hash: DISCLAIMER_HASH });
});

// ─── 1. Page loads with correct UI structure ──────────────────────────────────
test("homepage renders title and form", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Hold Em|Fold Em|holdemfoldemapp/i);

  // h1 contains "Hold" (green) and "Fold" (red) spans
  await expect(page.locator("h1")).toContainText("Hold");
  await expect(page.locator("h1")).toContainText("Fold");

  // Ticker input — actual placeholder is "AAPL · SPY · QQQ · BTC-USD"
  await expect(page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD")).toBeVisible();

  await expect(page.getByRole("button", { name: /analyze/i })).toBeVisible();
});

// ─── 2. Analyze button is disabled until a symbol is typed ───────────────────
test("analyze button disabled when input is empty", async ({ page }) => {
  await page.goto("/");

  const button = page.getByRole("button", { name: /analyze/i });
  await expect(button).toBeDisabled();

  await page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD").fill("AAPL");
  await expect(button).toBeEnabled();

  await page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD").clear();
  await expect(button).toBeDisabled();
});

// ─── 3. Input auto-uppercases typed symbol ────────────────────────────────────
test("symbol input auto-uppercases characters", async ({ page }) => {
  await page.goto("/");

  const input = page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD");
  await input.fill("aapl");
  await expect(input).toHaveValue("AAPL");
});

// ─── 4. Period pills exist with expected values ───────────────────────────────
test("period pill buttons have correct labels", async ({ page }) => {
  await page.goto("/");

  for (const label of ["1M", "3M", "6M", "1Y", "2Y"]) {
    await expect(page.getByRole("button", { name: label })).toBeVisible();
  }
});

// ─── 5. Options strategy panel toggles open and closed ───────────────────────
test("options strategy panel toggles open and shows strategies", async ({ page }) => {
  await page.goto("/");

  // DTE label is inside the panel; should be hidden initially
  const dteLabel = page.getByText("Days to Expiration (DTE)");
  await expect(dteLabel).not.toBeVisible();

  // Click toggle button to open options panel
  const toggleButton = page.locator("button").filter({ hasText: /Add Options Strategy/i });
  await toggleButton.click();
  await expect(dteLabel).toBeVisible();
  await expect(page.getByRole("button", { name: /Long Call/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Iron Condor/i })).toBeVisible();

  // Click toggle button again to close
  const toggleClosedButton = page.locator("button").filter({ hasText: /Options Mode/i });
  await toggleClosedButton.click();
  await expect(dteLabel).not.toBeVisible();
});

// ─── 6. Backend error surfaces a human-readable message in the UI ─────────────
test("shows error message when backend returns an error", async ({ page }) => {
  // Set up route interception before navigation
  await page.route("**/api/analyze", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Backend unavailable" }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD").fill("SPY");
  await page.getByRole("button", { name: /analyze/i }).click();

  // Should display error message or red-colored error container
  await expect(page.locator("text=Backend unavailable")).toBeVisible({ timeout: 10_000 });
});

// ─── 7. Disclaimer modal appears on first visit (no localStorage) ─────────────
test("disclaimer modal appears when not yet acknowledged", async ({ page }) => {
  // Override the beforeEach seed — remove the ack key so modal fires
  await page.addInitScript(({ key }) => {
    localStorage.removeItem(key);
  }, { key: DISCLAIMER_KEY });

  await page.goto("/");

  // Modal should be visible — scope the text check inside the dialog to avoid
  // strict-mode violation (same text appears in the footer and button label)
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Not investment advice.").first()).toBeVisible();

  // Clicking "I understand" should dismiss it
  await page.getByRole("button", { name: /I understand/i }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();

  // localStorage should now be set
  const stored = await page.evaluate(
    ({ key }) => localStorage.getItem(key),
    { key: DISCLAIMER_KEY }
  );
  expect(stored).toBe(DISCLAIMER_HASH);
});

// ─── 8. Uncapped-risk banner shows for strategies with unlimited max_loss ──────
test("uncapped-risk warning appears when max_loss is null", async ({ page }) => {
  await page.route("**/api/analyze", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        symbol: "SPY", asset_type: "options", verdict: "HOLD EM",
        confidence: 70, price: 500, bias: "bullish", risk_level: "high",
        cached: false, bullish_count: 3, bearish_count: 1, avg_score: 65,
        top_signals: [], rsi: null, macd: null, adx: null, atr: null,
        volatility_regime: "normal", volume_spike: null, suppressions: [],
        trade_timeframe: null, entry: null, stop: null, target: null,
        risk_reward: null, stop_pct: null, upside_pct: null,
        vehicle: null, vehicle_notes: null, primary_signal: null, supporting_signals: [],
        position_qty: null, position_entry: null, position_side: "long",
        position_pnl_pct: null, position_pnl_dollar: null,
        position_vs_stop: null, position_vs_target: null,
        position_aging: null, position_pnl_detail: null,
        fib_levels: [], fib_confluence_zones: [],
        nearest_fib_support: null, nearest_fib_resistance: null,
        options_greeks: null,
        options_strategy: "long_call",
        options_legs: null,
        dte: 30,
        net_premium: -1.50,
        max_profit: null,   // null triggers the uncapped banner
        max_loss: null,
        breakeven_prices: null, spread_width: null, pop: null,
        payoff_curve: null, strategy_note: null,
        summary: "Test summary.", data_timestamp: null,
        degraded: false, warnings: [], request_id: "test-123",
        disclaimer_version: "1.0",
      }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD").fill("SPY");
  await page.getByRole("button", { name: /analyze/i }).click();

  // The uncapped-risk warning should appear in the verdict card
  await expect(page.getByText(/Uncapped or very large maximum loss/i)).toBeVisible({ timeout: 10_000 });
});

// ─── 9. Multi-lot position panel: add/remove lots and render ──────────────────
test("multi-lot position panel adds and removes lots", async ({ page }) => {
  await page.goto("/");

  // Expand the position panel
  await page.getByRole("button", { name: /Add existing position/i }).click();

  // Initially one lot visible — "Lot 1" label
  await expect(page.getByText("Lot 1")).toBeVisible();

  // Add a second lot
  await page.getByRole("button", { name: /Add another lot/i }).click();
  await expect(page.getByText("Lot 2")).toBeVisible();

  // Remove the second lot via the × button (second one in the list)
  const removeButtons = page.locator("button", { hasText: "×" });
  await removeButtons.last().click();
  await expect(page.getByText("Lot 2")).not.toBeVisible();
  await expect(page.getByText("Lot 1")).toBeVisible();
});
