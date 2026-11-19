import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_SMOKE_PORT || 8765);
const baseUrl = "http://127.0.0.1:" + port;
const server = spawn(process.env.PYTHON || "python", [
  "scripts/ui_api_smoke_server.py", "--port", String(port),
], { stdio: "ignore" });

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(baseUrl);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("UI smoke server did not start");
}

(async () => {
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, acceptDownloads: true });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("https://fonts.googleapis.com/**", route =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" })
    );
    let resolveAnalyticsStarted;
    let releaseAnalytics;
    const analyticsStarted = new Promise(resolve => { resolveAnalyticsStarted = resolve; });
    const analyticsGate = new Promise(resolve => { releaseAnalytics = resolve; });
    const analyticsRequests = [];
    page.on("request", request => {
      const requestUrl = new URL(request.url());
      if (requestUrl.pathname === "/api/publishing/analytics-history") {
        analyticsRequests.push(requestUrl.toString());
      }
    });
    await page.route("**/api/publishing/analytics-history", async route => {
      resolveAnalyticsStarted();
      await analyticsGate;
      await route.continue();
    });

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    fs.mkdirSync("artifacts", { recursive: true });
    assert.match(await page.title(), /NEXUS STUDIO PRO/);
    assert.equal(await page.locator(".main-nav a").count(), 5);
    assert.equal(await page.locator("#studio").count(), 1);
    assert.equal(await page.locator("#discovery").count(), 1);
    assert.equal(await page.locator("#review").count(), 1);
    assert.equal(await page.locator("#operations").count(), 1);
    assert.equal(await page.locator("#connection").getAttribute("role"), "status");

    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill("nexus-ui-browser-smoke-token-2026-11-19-32chars");
    await page.locator("#saveToken").click();
    await page.locator("#settingsDialog").waitFor({ state: "hidden" });
    await page.locator("#loadAnalyticsHistory").click();
    await analyticsStarted;
    assert.equal(await page.locator("#analyticsHistory").getAttribute("aria-busy"), "true");
    releaseAnalytics();
    await page.waitForFunction(() =>
      document.querySelector("#analyticsHistory").getAttribute("aria-busy") === "false" &&
      document.querySelector("#analyticsHistoryStatus").textContent.includes("기준 시각")
    );
    assert.equal(await page.locator("#exportAnalyticsHistory").isDisabled(), false);
    await page.screenshot({ path: "artifacts/nexus-dashboard-desktop.png", fullPage: true });
    const downloadPromise = page.waitForEvent("download");
    await page.locator("#exportAnalyticsHistory").click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /\.csv$/);
    const downloadPath = await download.path();
    const csv = fs.readFileSync(downloadPath, "utf8");
    assert.equal(csv.split(/\r?\n/).length, 503);
    assert.ok(csv.includes("browser-yt-001"));
    assert.ok(csv.includes("browser-yt-500"));
    assert.ok(csv.includes("browser-yt-501"));
    assert.ok(csv.includes("browser-tt-001"));
    assert.ok(analyticsRequests.some(url => new URL(url).searchParams.has("before_id")), "CSV export must request a real keyset-cursor page");
    await page.waitForFunction(() => document.querySelector("#analyticsHistoryStatus").textContent.includes("CSV 다운로드 요청 완료"));
    assert.match(await page.locator("#analyticsHistoryStatus").textContent(), /CSV 다운로드 요청 완료/);

    failQueueStats = true;
    await page.locator("#refreshAll").click();
    await page.waitForFunction(() =>
      document.querySelector("#connection").textContent.includes("API 부분 연결")
    );
    assert.match(await page.locator("#toast").textContent(), /일부 데이터 갱신 실패/);
    failQueueStats = false;

    await page.reload({ waitUntil: "networkidle" });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains("skip-link")), true);
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.activeElement.id), "home");

    for (const section of ["studio", "discovery", "review", "operations"]) {
      const link = page.locator('.main-nav a[href="#' + section + '"]');
      await link.click();
      assert.equal(await link.getAttribute("aria-current"), "page");
    }

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.waitForTimeout(100);
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        document: document.documentElement.scrollWidth,
      }));
      assert.ok(
        dimensions.document <= dimensions.viewport,
        "horizontal page overflow at " + width + "px: " + JSON.stringify(dimensions)
      );
      const targets = await page.locator(".main-nav a").evaluateAll(links =>
        links.map(link => {
          const rect = link.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        })
      );
      assert.ok(targets.every(rect => rect.width >= 48 && rect.height >= 48),
        "compact navigation touch targets must be at least 48px");
    }

    await page.screenshot({ path: "artifacts/nexus-dashboard-mobile.png", fullPage: true });
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await page.locator("html").evaluate(el => getComputedStyle(el).scrollBehavior), "auto");
    assert.deepEqual(pageErrors, []);
    process.stdout.write("UI browser smoke passed: desktop/mobile, keyboard navigation, analytics busy/as-of state, paginated 502-row CSV download, partial API failure feedback, reduced motion.\n");
  } catch (error) {
    process.stderr.write((error && error.stack) || String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
