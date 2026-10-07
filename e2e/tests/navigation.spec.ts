import { test, expect } from "@playwright/test";

async function orionReachable() {
  try {
    const res = await fetch("http://127.0.0.1:8001/health", { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

test("ORION stack pills link to each stack UI in a new tab", async ({ page }) => {
  test.skip(!(await orionReachable()), "ORION stack not running on :8001");
  await page.goto("http://127.0.0.1:8001/ui/");
  await expect(page.locator("h1.title")).toContainText("ORION CI/CD");
  const hub = page.locator('a.orion-nav-pill[href="http://127.0.0.1:5180"]');
  const consoleLink = page.locator('a.orion-nav-pill[href="http://127.0.0.1:5173"]');
  const platform = page.locator('a.orion-nav-pill[href="http://127.0.0.1:3000"]');
  await expect(hub).toHaveAttribute("target", "_blank");
  await expect(consoleLink).toHaveAttribute("target", "_blank");
  await expect(platform).toHaveAttribute("target", "_blank");
  await expect(page.locator("span.orion-nav-pill--active")).toContainText("ORION");
});
