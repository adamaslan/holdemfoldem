import { test, expect } from "@playwright/test";

// ─── 1. Page loads with correct UI structure ──────────────────────────────────
test("homepage renders title and form", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Hold Em|Fold Em|holdemfoldemapp/i);
  await expect(page.getByText("Hold Em")).toBeVisible();
  await expect(page.getByText("Fold Em")).toBeVisible();
  await expect(page.getByPlaceholder(/ticker symbol/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /analyze/i })).toBeVisible();
});

// ─── 2. Analyze button is disabled until a symbol is typed ───────────────────
test("analyze button disabled when input is empty", async ({ page }) => {
  await page.goto("/");

  const button = page.getByRole("button", { name: /analyze/i });
  await expect(button).toBeDisabled();

  await page.getByPlaceholder(/ticker symbol/i).fill("AAPL");
  await expect(button).toBeEnabled();

  await page.getByPlaceholder(/ticker symbol/i).clear();
  await expect(button).toBeDisabled();
});

// ─── 3. Input auto-uppercases typed symbol ────────────────────────────────────
test("symbol input auto-uppercases characters", async ({ page }) => {
  await page.goto("/");

  const input = page.getByPlaceholder(/ticker symbol/i);
  await input.fill("aapl");
  await expect(input).toHaveValue("AAPL");
});

// ─── 4. Dropdowns contain expected period and asset-type options ──────────────
test("period and asset-type selects have correct options", async ({ page }) => {
  await page.goto("/");

  // Asset type options
  const assetSelect = page.locator("select").first();
  await expect(assetSelect.locator("option")).toHaveCount(3);
  await expect(assetSelect.locator("option[value='stock']")).toBeAttached();
  await expect(assetSelect.locator("option[value='etf']")).toBeAttached();
  await expect(assetSelect.locator("option[value='options']")).toBeAttached();

  // Period options
  const periodSelect = page.locator("select").nth(1);
  for (const p of ["1mo", "3mo", "6mo", "1y"]) {
    await expect(periodSelect.locator(`option[value='${p}']`)).toBeAttached();
  }
});

// ─── 5. Backend error surfaces a human-readable message in the UI ─────────────
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
  await page.getByPlaceholder(/ticker symbol/i).fill("SPY");
  await page.getByRole("button", { name: /analyze/i }).click();

  // Should display an error — not crash or hang
  await expect(page.locator("text=Backend unavailable").or(page.locator("[class*='red']").first())).toBeVisible({ timeout: 8_000 });
});
