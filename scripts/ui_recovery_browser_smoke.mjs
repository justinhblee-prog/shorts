import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_RECOVERY_SMOKE_PORT || 8766);
const baseUrl = "http://127.0.0.1:" + port;
const token = "nexus-recovery-browser-smoke-token-2026-11-20-32chars";
const jobId = "browser-smoke-quarantine-001";
const server = spawn(process.env.PYTHON || "python", [
  "scripts/ui_recovery_api_smoke_server.py", "--port", String(port),
], { stdio: "ignore" });

async function waitForServer() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(baseUrl);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Recovery UI smoke server did not start");
}

(async () => {
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    page.setDefaultTimeout(10000);
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    assert.match(await page.title(), /NEXUS STUDIO PRO/);

    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill(token);
    await page.locator("#reviewerInput").fill("recovery-smoke-operator");
    await page.locator("#saveToken").click();
    await page.locator("#settingsDialog").waitFor({ state: "hidden" });
    await page.locator("#loadDevelopmentJobs").click();

    const recoverButton = page.locator('[data-recover-development-job="' + jobId + '"]');
    await recoverButton.waitFor({ state: "visible" });
    assert.equal(await recoverButton.isEnabled(), true);
    assert.match(await page.locator("#developmentJobList").textContent(), /격리/);
    assert.equal(await page.locator('#developmentJobList [data-workstream="UI"]').count(), 1,
      "UI-scoped jobs must appear in their own workstream lane");
    assert.equal(await page.locator('#developmentJobList [data-workstream="CORE"]').count(), 1,
      "backend-scoped jobs must appear in the Core workstream lane");
    const dependencyBoard = await page.locator("#developmentJobList").textContent();
    assert.match(dependencyBoard, /선행 작업/);
    assert.match(dependencyBoard, /Browser smoke UI dependency/);
    assert.match(dependencyBoard, /완료/);
    await page.setViewportSize({ width: 320, height: 900 });
    const mobileLayout = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    assert.ok(mobileLayout.content <= mobileLayout.viewport,
      "multi-flow workstream board must not overflow a 320px mobile viewport");
    assert.equal(await page.locator('#developmentJobList [data-workstream="UI"]').count(), 1);
    await page.setViewportSize({ width: 1440, height: 960 });

    page.on("dialog", async dialog => {
      if (dialog.type() === "prompt") {
        await dialog.accept("Reviewed the quarantined job and corrected its source scope.");
      } else if (dialog.type() === "confirm") {
        await dialog.accept();
      } else {
        await dialog.dismiss();
      }
    });
    const recoveryResponse = page.waitForResponse(response =>
      response.url().includes("/api/development/jobs/" + jobId + "/recover") &&
      response.request().method() === "POST"
    );
    await recoverButton.click();
    const response = await recoveryResponse;
    assert.equal(response.status(), 200, "operator recovery endpoint must return HTTP 200");

    await page.waitForFunction(id => {
      const item = document.querySelector('[data-development-job="' + id + '"]');
      const card = item?.closest(".development-job-card");
      return card && card.textContent.includes("대기") &&
        !card.querySelector("[data-recover-development-job]");
    }, jobId);
    await page.locator('[data-development-job="' + jobId + '"]').click();
    await page.waitForFunction(() =>
      document.querySelector("#developmentJobEvents").textContent.includes("quarantine_recovered")
    );
    const events = await page.evaluate(async ({ tokenValue, id }) => {
      const result = await fetch("/api/development/jobs/" + encodeURIComponent(id) + "/events?limit=100", {
        headers: { "X-Review-Token": tokenValue },
      });
      return { status: result.status, body: await result.json() };
    }, { tokenValue: token, id: jobId });
    assert.equal(events.status, 200);
    const recovery = events.body.events.find(event => event.event_type === "quarantine_recovered");
    assert.ok(recovery, "immutable quarantine recovery event must be present");
    assert.equal(recovery.actor, "legacy-operator", "legacy shared-token authentication must own the immutable recovery event");
    assert.equal(recovery.details.reason, "Reviewed the quarantined job and corrected its source scope.");
    assert.deepEqual(pageErrors, []);
    process.stdout.write("UI recovery browser smoke passed: authenticated dashboard, quarantine state, operator-confirmed recovery, ready state, immutable audit attribution.\n");
  } catch (error) {
    process.stderr.write((error && error.stack) || String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
