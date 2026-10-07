import { test, expect } from "@playwright/test";

test("Operations center API returns policy/security/performance panels", async ({ page }) => {
  const resp = await page.request.get("/api/v1/control-plane/operations");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body).toHaveProperty("policy_panel");
  expect(body).toHaveProperty("security_panel");
  expect(body).toHaveProperty("performance_panel");
  expect(Array.isArray(body.top_blockers)).toBeTruthy();
});
