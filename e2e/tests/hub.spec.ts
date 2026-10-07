import { test, expect } from "@playwright/test";

test("Command Hub renders stack cards", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText("ORION Command Hub");
  await expect(page.locator("#hub-grid a.hub-card")).toHaveCount(3);
  await expect(page.locator(".hub-intel-section h2")).toContainText("Cross-stack intelligence");
});

test("Hub health polling updates badges", async ({ page }) => {
  await page.goto("/");
  await page.waitForTimeout(1500);
  const badges = page.locator(".hub-card__badge");
  await expect(badges.first()).toBeVisible();
});

test("Unified control plane section renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#control-plane h2")).toContainText("Unified control plane");
  await expect(page.locator("#cp-health .cp-health-card")).toHaveCount(3, {
    timeout: 15_000,
  });
  await expect(page.locator("#control-plane .cp-table")).toBeVisible();
  await expect(page.locator("#cp-refresh")).toBeEnabled();
});

test("Control plane health API responds", async ({ page }) => {
  const resp = await page.request.get("/api/v1/control-plane/health");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.hub_status).toBe("ok");
  expect(Array.isArray(body.stacks)).toBeTruthy();
});

test("Hub stack nav links open other stacks in new tabs", async ({ page }) => {
  await page.goto("/");
  const orion = page.locator('a.hub-nav-pill[href="http://127.0.0.1:8001/ui/"]');
  await expect(orion).toHaveAttribute("target", "_blank");
  await expect(orion).toHaveAttribute("rel", /noopener/);
  const consoleLink = page.locator('a.hub-nav-pill[href="http://127.0.0.1:5173"]');
  await expect(consoleLink).toHaveAttribute("target", "_blank");
});
