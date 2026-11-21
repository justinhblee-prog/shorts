import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_DEVELOPMENT_MONITOR_SMOKE_PORT || 8766);
const baseUrl = "http://127.0.0.1:" + port;
const validToken = "development-monitor-smoke-valid-token";
const server = spawn(process.env.PYTHON || "python", [
  "scripts/ui_development_monitor_smoke_server.py", "--port", String(port),
], { stdio: ["ignore", "pipe", "pipe"] });

async function waitForServer() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(baseUrl + "/__test__/health");
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Development monitor fixture server did not start");
}

async function fixtureRequests() {
  const response = await fetch(baseUrl + "/__test__/requests");
  assert.equal(response.status, 200);
  return (await response.json()).requests;
}

(async () => {
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("https://fonts.googleapis.com/**", route =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" })
    );

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    assert.match(await page.title(), /NEXUS STUDIO PRO/);
    assert.equal(await page.locator("#development").count(), 1);
    assert.equal(await page.locator("#developmentJobs").count(), 1);

    // Without authentication, opening or refreshing the monitor must not issue API calls.
    await page.locator("#refreshDevelopment").click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentConnectionNote").textContent.includes("운영 인증")
    );
    assert.equal((await fixtureRequests()).filter(item => item.path.startsWith("/api/development/")).length, 0);

    // Invalid credentials fail closed and do not issue any write request.
    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill("invalid-monitor-token");
    await page.locator("#saveToken").click();
    await page.locator("#settingsDialog").waitFor({ state: "hidden" }).catch(() => {});
    await page.locator("#refreshDevelopment").click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentConnectionNote").textContent.includes("개발 작업 DB 연결 안 됨")
    );
    assert.equal(await page.locator("#developmentMetricTotal").textContent(), "—");

    // Valid credentials load the real monitor UI against deterministic fixtures.
    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill(validToken);
    await page.locator("#saveToken").click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentMetricTotal").textContent === "2" &&
      document.querySelector("#developmentMetricReady").textContent === "1"
    );
    assert.match(await page.locator("#developmentConnectionNote").textContent(), /읽기 전용/);

    const jobs = page.locator("#developmentJobs");
    await page.locator("#developmentStatusFilter").selectOption("ready");
    await page.waitForFunction(() =>
      document.querySelectorAll("#developmentJobs .development-job-card").length === 1
    );
    assert.match(await jobs.textContent(), /BUILD-SMOKE-001/);
    assert.doesNotMatch(await jobs.textContent(), /BUILD-SMOKE-002/);

    await jobs.locator('[data-development-job="BUILD-SMOKE-001"]').click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentSelectedJob").textContent === "BUILD-SMOKE-001"
    );
    assert.match(await page.locator("#developmentEvents").textContent(), /queued/);

    await page.locator("#developmentStatusFilter").selectOption("");
    await page.waitForFunction(() =>
      document.querySelectorAll("#developmentJobs .development-job-card").length === 2
    );
    await jobs.locator('[data-development-job="BUILD-SMOKE-002"]').click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentSelectedJob").textContent === "BUILD-SMOKE-002"
    );
    assert.match(await page.locator("#developmentEvents").textContent(), /blocked/);

    const rendered = await page.locator("body").innerText();
    for (const secret of [
      "SECRET_LEASE_TOKEN", "SECRET_RUNNER_HOST", "SECRET_JOB_DETAILS",
      "SECRET_PRIVATE_EVENT_DETAILS",
    ]) assert.equal(rendered.includes(secret), false, "private monitor data leaked into the browser");

    const requests = await fixtureRequests();
    assert.ok(requests.some(item => item.path === "/api/development/summary" && item.method === "GET"));
    assert.ok(requests.some(item => item.path === "/api/development/jobs" && item.method === "GET"));
    assert.ok(requests.some(item => item.path.endsWith("/events") && item.method === "GET"));
    assert.equal(requests.filter(item =>
      item.path.startsWith("/api/development/") && item.method !== "GET"
    ).length, 0, "the monitor must never issue a mutation request");

    fs.mkdirSync("artifacts", { recursive: true });
    await page.screenshot({ path: "artifacts/development-monitor-desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: "artifacts/development-monitor-mobile.png", fullPage: true });
    assert.deepEqual(pageErrors, []);
    process.stdout.write("Development monitor browser smoke passed: auth states, summary, status filter, job selection, event switching, private-field redaction, GET-only behavior.\n");
  } catch (error) {
    process.stderr.write((error && error.stack) || String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
