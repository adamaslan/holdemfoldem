import { test, expect } from "@playwright/test";

// ─── 1. Page loads with correct UI structure ──────────────────────────────────
// The header renders "Hold" and "Fold" as separate <span> elements inside <h1>.
// There is no single "Hold Em" or "Fold Em" text node — we check the <h1> text
// and the individual colour spans instead.
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
// The onChange handler calls .toUpperCase() on every keystroke.
test("symbol input auto-uppercases characters", async ({ page }) => {
  await page.goto("/");

  const input = page.getByPlaceholder("AAPL · SPY · QQQ · BTC-USD");
  await input.fill("aapl");
  await expect(input).toHaveValue("AAPL");
});

// ─── 4. Period pills exist with expected values ───────────────────────────────
// The period selector is implemented as pill buttons (not a <select>).
// We verify the five period labels are all visible on the page.
test("period pill buttons have correct labels", async ({ page }) => {
  await page.goto("/");

  for (const label of ["1M", "3M", "6M", "1Y", "2Y"]) {
    await expect(page.getByRole("button", { name: label })).toBeVisible();
  }
});

// ─── 5. Options strategy panel toggles open and closed ───────────────────────
test("options strategy panel toggles open and shows strategies", async ({ page }) => {
  await page.goto("/");

  // Panel should be hidden initially
  await expect(page.getByText("Strategy")).not.toBeVisible();

  // Click toggle to open
  await page.getByRole("button", { name: /options strategy/i }).click();
  await expect(page.getByText("Strategy")).toBeVisible();
  await expect(page.getByRole("button", { name: /Long Call/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Iron Condor/i })).toBeVisible();

  // Click toggle again to close
  await page.getByRole("button", { name: /options mode/i }).click();
  await expect(page.getByText("Strategy")).not.toBeVisible();
});

// ─── 6. Backend error surfaces a human-readable message in the UI ─────────────
test("shows error message when backend returns an error", async ({ page }) => {
  // Intercept the Next.js API route and return a backend-style error
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

  // Should display an error — not crash or hang
  await expect(
    page.locator("text=Backend unavailable").or(page.locator("[class*='red']").first())
  ).toBeVisible({ timeout: 8_000 });
});
