import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_SMOKE_PORT || 8765);
const baseUrl = "http://127.0.0.1:" + port;
const server = spawn(process.env.PYTHON || "python", [
  "scripts/ui_smoke_server.py", "--port", String(port),
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("https://fonts.googleapis.com/**", route =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" })
    );
    let authenticated = false;
    await page.route("**/api/**", async route => {
      if (!authenticated) {
        return route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Authentication required" }),
        });
      }
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === "/api/publishing/analytics-history") {
        await new Promise(resolve => setTimeout(resolve, 350));
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: { youtube: [], tiktok: [] },
            as_of: "2026-11-19T09:00:00+00:00",
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
    });

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    fs.mkdirSync("artifacts", { recursive: true });
    await page.screenshot({ path: "artifacts/nexus-dashboard-desktop.png", fullPage: true });
    assert.match(await page.title(), /NEXUS STUDIO PRO/);
    assert.equal(await page.locator(".main-nav a").count(), 5);
    assert.equal(await page.locator("#studio").count(), 1);
    assert.equal(await page.locator("#discovery").count(), 1);
    assert.equal(await page.locator("#review").count(), 1);
    assert.equal(await page.locator("#operations").count(), 1);
    assert.equal(await page.locator("#connection").getAttribute("role"), "status");

    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill("browser-smoke-token");
    authenticated = true;
    await page.locator("#saveToken").click();
    await page.locator("#settingsDialog").waitFor({ state: "hidden" });
    await page.locator("#loadAnalyticsHistory").click();
    assert.equal(await page.locator("#analyticsHistory").getAttribute("aria-busy"), "true");
    await page.waitForFunction(() =>
      document.querySelector("#analyticsHistory").getAttribute("aria-busy") === "false" &&
      document.querySelector("#analyticsHistoryStatus").textContent.includes("기준 시각")
    );
    assert.equal(await page.locator("#exportAnalyticsHistory").isDisabled(), true);

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
    process.stdout.write("UI browser smoke passed: desktop, 390px/320px layouts, navigation, keyboard skip, reduced motion.\n");
  } catch (error) {
    process.stderr.write((error && error.stack) || String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
