import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_PREVIEW_SMOKE_PORT || 8766);
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
  throw new Error("Preview accessibility smoke server did not start");
}

(async () => {
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: () => Promise.reject(new Error("clipboard permission denied")) },
      });
    });
    page.setDefaultTimeout(10000);
    const apiRequests = [];
    await page.route("**/api/**", async route => {
      apiRequests.push({ method: route.request().method(), url: route.request().url() });
      await route.abort();
    });
    await page.goto(baseUrl + "/?nexus-preview-test=1", { waitUntil: "domcontentloaded" });

    const banner = page.locator(".nexus-preview-banner");
    assert.equal(await banner.getAttribute("role"), "status");
    assert.equal(await banner.getAttribute("aria-live"), "polite");
    assert.match(await banner.innerText(), /운영 API\/실제 계정 데이터와 분리/);
    assert.equal(await page.locator("#connection").getAttribute("aria-label"), "화면 미리보기, 운영 API 미연결");

    // Keyboard focus must be visible and the floating action must have a stable name.
    await page.keyboard.press("Tab");
    const firstFocus = await page.evaluate(() => ({
      tag: document.activeElement.tagName,
      outlineStyle: getComputedStyle(document.activeElement).outlineStyle,
      outlineWidth: getComputedStyle(document.activeElement).outlineWidth,
    }));
    assert.notEqual(firstFocus.outlineStyle, "none");
    assert.ok(parseFloat(firstFocus.outlineWidth) >= 2);
    const toggle = page.getByRole("button", { name: "화면 피드백" });
    assert.equal(await toggle.getAttribute("aria-controls"), "nexusFeedbackPanel");
    await toggle.click();
    assert.equal(await toggle.getAttribute("aria-expanded"), "true");
    const panel = page.locator("#nexusFeedbackPanel");
    assert.equal(await panel.isVisible(), true);
    const feedbackInput = page.getByLabel("수정할 화면과 내용을 적어주세요");
    assert.equal(await feedbackInput.evaluate(node => node === document.activeElement), true);
    await feedbackInput.fill("모바일 카드 간격을 줄여주세요.");
    await page.getByRole("button", { name: "피드백 복사" }).click();
    assert.match(await feedbackInput.inputValue(), /\[NEXUS 화면 피드백\]/);
    assert.match(await page.locator(".nexus-feedback-status").innerText(), /자동 복사를 사용할 수 없어 텍스트를 선택/);
    assert.equal(await feedbackInput.evaluate(node => node === document.activeElement), true);
    assert.ok(await feedbackInput.evaluate(node => node.selectionEnd > node.selectionStart));

    await page.keyboard.press("Escape");
    assert.equal(await panel.isVisible(), false);
    assert.equal(await toggle.getAttribute("aria-expanded"), "false");
    assert.equal(await toggle.evaluate(node => node === document.activeElement), true);

    // The preview must remain read-only at narrow widths and keep its controls on-screen.
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.waitForTimeout(50);
      const bounds = await page.locator(".nexus-feedback-toggle").boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width,
        "feedback control must remain within " + width + "px viewport");
      const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      assert.ok(pageWidth <= width, "horizontal overflow at " + width + "px: " + pageWidth);
    }
    for (const id of ["openSettings", "openSettingsNav"]) {
      const control = page.locator("#" + id);
      if (await control.count()) assert.equal(await control.isDisabled(), true);
    }
    for (const id of ["productionForm", "trendForm", "competitorForm", "opportunityForm", "scheduleForm", "ledgerForm"]) {
      const form = page.locator("#" + id);
      if (await form.count()) {
        const submits = form.locator('button[type="submit"],button:not([type])');
        for (let index = 0; index < await submits.count(); index += 1) {
          assert.equal(await submits.nth(index).isDisabled(), true, "preview submit must remain disabled: " + id);
        }
      }
    }
    assert.equal(apiRequests.some(request => request.method !== "GET"), false,
      "visual preview must never submit operational API mutations");
    process.stdout.write("[preview-a11y-smoke] PASS: keyboard, feedback focus/escape/copy fallback, 390px/320px layout, read-only guard\n");
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => {
  process.stderr.write(String(error.stack || error) + "\n");
  process.exitCode = 1;
});