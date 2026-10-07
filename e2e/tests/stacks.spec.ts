import { test, expect } from "@playwright/test";

async function fetchReady(url: string) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
    return res;
  } catch {
    return null;
  }
}

function assertReadyWhenHealthy(label: string, url: string) {
  test(`${label} /ready when stack is running`, async () => {
    const res = await fetchReady(url);
    test.skip(!res, `${label} stack not running`);
    test.skip(!res!.ok, `${label} stack running but not ready`);
    const body = await res!.json();
    expect(body).toHaveProperty("ready");
  });
}

assertReadyWhenHealthy("canonical", "http://127.0.0.1:8000/ready");
assertReadyWhenHealthy("ORION", "http://127.0.0.1:8001/ready");
assertReadyWhenHealthy("devops", "http://127.0.0.1:8002/ready");
