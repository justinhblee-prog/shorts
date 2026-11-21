import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_PREVIEW_SMOKE_PORT || 8766);
const baseUrl = "http://127.0.0.1:" + port;
const server = spawn(process.env.PYTHON || "python", [
  "-m", "http.server", String(port), "--directory", "frontend",
], { stdio: "ignore" });

async function waitForServer() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(baseUrl + "/preview.html");
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Responsive preview smoke server did not start");
}

(async () => {
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/api/**", route => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ brands: [] }),
    }));

    await page.goto(baseUrl + "/preview.html", { waitUntil: "networkidle" });
    fs.mkdirSync("artifacts", { recursive: true });

    assert.match(await page.title(), /NEXUS STUDIO PRO.*Responsive Preview/);

    const device = page.locator("#device");
    const frame = page.locator("iframe");
    const app = page.frameLocator("iframe");
    assert.equal(await app.locator('link[href="/cyber-magic.css"]').count(), 1);
    await app.locator("body").evaluate(el => getComputedStyle(el).getPropertyValue("--violet").trim()).then(value => assert.equal(value, "#a58bff"));
    assert.equal(await app.locator(".topbar").evaluate(el => getComputedStyle(el).position), "fixed");
    assert.equal(await app.locator(".topbar").evaluate(el => Math.round(el.getBoundingClientRect().width)), 258);
    assert.equal(await app.locator(".studio-floor").count(), 1);
    assert.equal(await app.locator(".stage-node").count(), 4);
    assert.equal(await app.locator(".studio-rail").count(), 1);
    assert.equal(await app.locator("#studioMediaSpotlight").count(), 1);
    assert.match(await app.locator("#studioMediaSpotlight").textContent(), /검수 대기 영상/);
    assert.equal(await app.locator("#workspaceSearch").count(), 1);
    assert.equal(await app.locator(".main-nav a").count(), 9);
    assert.equal(await app.locator("#timelineEditor").count(), 1);
    assert.equal(await app.locator("#timelineSubmitRender").count(), 1);
    assert.equal(await app.locator("#timelineCreateWorkspace").count(), 1);
    assert.equal(await app.locator("#timelineAudioInput").count(), 1);
    assert.equal(await app.locator("#timelineRenderReview").count(), 1);
    assert.equal(await app.locator("#timelineMediaShelf").count(), 1);
    assert.equal(await app.locator("#timelineVisualTrack").count(), 1);
    assert.equal(await app.locator("#timelineSelectedMeta").count(), 1);
    assert.equal(await app.locator(".button-primary").first().evaluate(el => getComputedStyle(el).backgroundImage.includes("linear-gradient")), true);
    await frame.waitFor();
    await page.waitForFunction(() => {
      const frame = document.querySelector("iframe");
      return frame?.contentDocument?.readyState === "complete" &&
        frame.contentDocument.title.includes("NEXUS STUDIO PRO");
    });

    const expectedWidths = [
      ["desktop", "1440px"],
      ["tablet", "820px"],
      ["mobile", "390px"],
    ];
    for (const [mode, width] of expectedWidths) {
      await page.locator('[data-device="' + mode + '"]').click();
      await page.waitForFunction(expected =>
        getComputedStyle(document.querySelector("#device")).width === expected,
      width);
      assert.equal(await device.evaluate((el, expectedMode) => el.classList.contains(expectedMode), mode), true);
      assert.equal(await page.locator('[data-device="' + mode + '"]').getAttribute("aria-pressed"), "true");
    }

    await page.locator("#landscape").click();
    await page.waitForFunction(() =>
      getComputedStyle(document.querySelector("#device")).width === "844px" &&
      document.querySelector("#device").classList.contains("landscape")
    );
    assert.equal(await page.locator("#landscape").getAttribute("aria-pressed"), "true");

    await page.locator("#portrait").click();
    await page.waitForFunction(() => getComputedStyle(document.querySelector("#device")).width === "390px");

    await page.locator("#actual").click();
    assert.equal(await device.evaluate(el => getComputedStyle(el).transform), "matrix(1, 0, 0, 1, 0, 0)");
    assert.equal(await page.locator("#actual").getAttribute("aria-pressed"), "true");
    await page.locator("#fit").click();
    assert.equal(await page.locator("#fit").getAttribute("aria-pressed"), "true");

    await page.locator('[data-device="auto"]').click();
    await page.waitForFunction(() => {
      const el = document.querySelector("#device");
      const wrap = el.parentElement;
      const style = getComputedStyle(wrap);
      const available = wrap.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return el.classList.contains("auto") &&
        Math.abs(parseFloat(getComputedStyle(el).width) - available) <= 2;
    });
    const autoMeasurementsAt1600 = await device.evaluate(el => {
      const wrap = el.parentElement;
      const style = getComputedStyle(wrap);
      return {
        deviceWidth: parseFloat(getComputedStyle(el).width),
        availableWidth: wrap.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      };
    });
    const previewGeometryAt1600 = await page.evaluate(() =>
      ["body", ".stage", ".device-wrap", "#device"].map(selector => {
        const el = document.querySelector(selector);
        const rect = el.getBoundingClientRect();
        return { selector, width: rect.width, cssWidth: getComputedStyle(el).width, className: el.className };
      })
    );
    console.log("Auto preview geometry:", JSON.stringify(previewGeometryAt1600));
    assert.ok(
      Math.abs(autoMeasurementsAt1600.deviceWidth - autoMeasurementsAt1600.availableWidth) <= 2 &&
      autoMeasurementsAt1600.deviceWidth > 1000,
      "Auto mode must fill the wide preview viewport: " + JSON.stringify({ autoMeasurementsAt1600, previewGeometryAt1600 })
    );
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForFunction(() => {
      const el = document.querySelector("#device");
      const wrap = el.parentElement;
      const style = getComputedStyle(wrap);
      const available = wrap.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return Math.abs(parseFloat(getComputedStyle(el).width) - available) <= 2;
    });
    const autoWidthAt1280 = await device.evaluate(el => parseFloat(getComputedStyle(el).width));
    const previewGeometryAt1280 = await page.evaluate(() =>
      ["body", ".stage", ".device-wrap", "#device"].map(selector => {
        const el = document.querySelector(selector);
        const rect = el.getBoundingClientRect();
        return { selector, width: rect.width, cssWidth: getComputedStyle(el).width, transform: getComputedStyle(el).transform, className: el.className };
      })
    );
    console.log("Resized auto preview geometry:", JSON.stringify(previewGeometryAt1280));
    assert.ok(
      autoWidthAt1280 < autoMeasurementsAt1600.deviceWidth && autoWidthAt1280 > 1000,
      "Auto mode must follow browser resize and remain full-width: " + JSON.stringify({ autoWidthAt1280, previewGeometryAt1280 })
    );
    const previewScale = await device.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).a);
    assert.ok(previewScale > 0.8, "Auto fit scale should remain near 100%: " + previewScale);

    await page.screenshot({ path: "artifacts/nexus-responsive-preview.png", fullPage: true });

    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto(baseUrl + "/?preview-embed=1", { waitUntil: "networkidle" });
    const mobileDimensions = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
    }));
    const mobileWorkbenchColumns = await page.locator(".studio-floor-grid").evaluate(el => getComputedStyle(el).gridTemplateColumns);
    assert.ok(!mobileWorkbenchColumns.includes(","), "Studio workbench must stack into one column on mobile: " + mobileWorkbenchColumns);
    const mobileEditorColumns = await page.locator(".timeline-server-controls").evaluate(el => getComputedStyle(el).gridTemplateColumns);
    assert.ok(!mobileEditorColumns.includes(","), "Timeline server controls must stack on mobile: " + mobileEditorColumns);
    assert.ok(
      mobileDimensions.document <= mobileDimensions.viewport,
      "Dashboard horizontal overflow at 320px: " + JSON.stringify(mobileDimensions)
    );
    await page.screenshot({ path: "artifacts/nexus-dashboard-320px.png", fullPage: true });
    assert.deepEqual(pageErrors, []);
    process.stdout.write(
      "Responsive preview browser smoke passed: desktop/tablet/mobile widths, landscape, fit/100%, auto width and resize, 320px dashboard overflow, no uncaught page errors.\n"
    );
  } catch (error) {
    process.stderr.write((error && error.stack) || String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})();
