import assert from "node:assert/strict";
import fs from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const port = Number(process.env.UI_SMOKE_PORT || 8765);
const baseUrl = "http://127.0.0.1:" + port;
const server = spawn(process.env.PYTHON || "python", [
  "scripts/ui_api_smoke_server.py", "--port", String(port),
], { stdio: "ignore" });

function makeWavFixture(durationMs = 5000, sampleRate = 8000) {
  const channels=1,bitsPerSample=16,sampleCount=Math.round(sampleRate*durationMs/1000),dataBytes=sampleCount*channels*bitsPerSample/8;
  const wav=Buffer.alloc(44+dataBytes);wav.write("RIFF",0);wav.writeUInt32LE(36+dataBytes,4);wav.write("WAVE",8);wav.write("fmt ",12);wav.writeUInt32LE(16,16);
  wav.writeUInt16LE(1,20);wav.writeUInt16LE(channels,22);wav.writeUInt32LE(sampleRate,24);wav.writeUInt32LE(sampleRate*channels*bitsPerSample/8,28);
  wav.writeUInt16LE(channels*bitsPerSample/8,32);wav.writeUInt16LE(bitsPerSample,34);wav.write("data",36);wav.writeUInt32LE(dataBytes,40);return wav;
}

function waitForSignal(promise, label, timeoutMs = 15000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error(label + " timed out after " + timeoutMs + "ms")),
      timeoutMs,
    )),
  ]);
}

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
    page.setDefaultTimeout(10000);
    page.setDefaultNavigationTimeout(15000);
    const checkpoint = message => process.stdout.write("[ui-smoke] " + message + "\\n");
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    const remoteFontRequests = [];
    page.on("request", request => { if (/fonts\.(googleapis|gstatic)\.com/i.test(request.url())) remoteFontRequests.push(request.url()); });
    await page.route("https://fonts.googleapis.com/**", route =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" })
    );
    let resolveAnalyticsStarted;
    let releaseAnalytics;
    const analyticsStarted = new Promise(resolve => { resolveAnalyticsStarted = resolve; });
    const analyticsGate = new Promise(resolve => { releaseAnalytics = resolve; });
    let failQueueStats = false;
    let capturedTimelineEdl = null;
    let capturedTimelineDecision = null;
    let uploadedTimelineAsset = false;
    await page.route("**/api/queue/stats", async route => {
      if (failQueueStats) {
        return route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Injected queue stats outage for UI recovery smoke" }),
        });
      }
      return route.continue();
    });
    const analyticsRequests = [];
    let analyticsHistoryResponse = null;
    let resolveAnalyticsHistoryResponse;
    const analyticsHistoryResponsePromise = new Promise(resolve => {
      resolveAnalyticsHistoryResponse = resolve;
    });
    page.on("request", request => {
      const requestUrl = new URL(request.url());
      if (requestUrl.pathname === "/api/publishing/analytics-history") {
        analyticsRequests.push(requestUrl.toString());
      }
    });
    page.on("response", async response => {
      const responseUrl = new URL(response.url());
      if (responseUrl.pathname !== "/api/publishing/analytics-history") return;
      try {
        const payload = await response.json();
        analyticsHistoryResponse = {
          status: response.status(),
          counts: payload.counts || {},
          itemCounts: Object.fromEntries(
            Object.entries(payload.items || {}).map(([key, items]) => [
              key, Array.isArray(items) ? items.length : null,
            ])
          ),
        };
      } catch (error) {
        analyticsHistoryResponse = { status: response.status(), parseError: String(error) };
      }
      resolveAnalyticsHistoryResponse(analyticsHistoryResponse);
    });
    await page.route(url => url.pathname === "/api/publishing/analytics-history", async route => {
      resolveAnalyticsStarted();
      await analyticsGate;
      await route.continue();
    });
    await page.route(url => url.pathname.startsWith("/api/operator/workspaces/") && url.pathname.endsWith("/assets"), async route => {
      if (route.request().method() !== "POST") return route.continue();
      uploadedTimelineAsset = true;
      return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify({
        asset_id:"asset-smoke",workspace_id:"ws-smoke",original_name:"timeline-smoke.mp4",size_bytes:8,
        scan_status:"clean",scanner_status:"clean",renderable:true,
        media_metadata:{duration_ms:5000,byte_size:8,has_video:true,has_audio:false,video_streams:[{width:720,height:1280}],audio_streams:[]}
      })});
    });
    await page.route(url => url.pathname === "/api/timeline/edl/validate", async route => {
      capturedTimelineEdl = route.request().postDataJSON();
      return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({valid:true,rendered:false,workspace_id:"ws-smoke",edl:capturedTimelineEdl})});
    });
    await page.route(url => /\/api\/operator\/workspaces\/[^/]+\/renders$/.test(url.pathname), async route => {
      if (route.request().method() !== "POST") return route.continue();
      const payload=route.request().postDataJSON();
      capturedTimelineEdl=payload.edl;
      return route.fulfill({status:202,contentType:"application/json",body:JSON.stringify({snapshot_id:"snapshot-smoke",render_job_id:"job-smoke",status:"queued",idempotent_replay:false})});
    });
    await page.route(url => /\/api\/operator\/workspaces\/[^/]+\/renders\/snapshot-smoke$/.test(url.pathname), async route => {
      return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({snapshot_id:"snapshot-smoke",render_job_id:"job-smoke",status:"review_pending",attempt:1,max_attempts:3})});
    });
    await page.route(url => /\/api\/operator\/workspaces\/[^/]+\/render-artifacts$/.test(url.pathname), async route => {
      return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({items:[{artifact_id:"artifact-smoke",snapshot_id:"snapshot-smoke",duration_ms:5000,byte_size:8,status:"review_pending"}]})});
    });
    await page.route(url => /\/api\/operator\/workspaces\/[^/]+\/render-artifacts\/artifact-smoke\/download$/.test(url.pathname), async route => {
      return route.fulfill({status:200,contentType:"video/mp4",body:Buffer.from("fake-mp4")});
    });
    await page.route(url => /\/api\/operator\/workspaces\/[^/]+\/renders\/snapshot-smoke\/decision$/.test(url.pathname), async route => {
      capturedTimelineDecision=route.request().postDataJSON();
      return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({snapshot_id:"snapshot-smoke",decision:capturedTimelineDecision.decision})});
    });

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    fs.mkdirSync("artifacts", { recursive: true });
    assert.match(await page.title(), /NEXUS STUDIO PRO/);
    assert.equal(await page.locator('link[href="/nexus-premium.css"]').count(), 1);
    const visualSystem = await page.evaluate(() => ({
      font: getComputedStyle(document.body).fontFamily,
      background: getComputedStyle(document.body).backgroundColor,
      heroColumns: getComputedStyle(document.querySelector(".hero")).gridTemplateColumns,
      koreanReplacementGlyphs: (document.body.innerText.match(/\uFFFD/g) || []).length,
      premiumStylesheet: [...document.styleSheets].some(sheet => sheet.href?.endsWith("/nexus-premium.css")),
      approvedStylesheet: [...document.styleSheets].some(sheet => sheet.href?.endsWith("/nexus-approved-design.css")),
      sidebarWidth: getComputedStyle(document.querySelector(".topbar")).width,
      mainOffset: getComputedStyle(document.querySelector("main")).marginLeft,
      violetAccent: getComputedStyle(document.body).getPropertyValue("--violet").trim(),
    }));
    assert.match(visualSystem.font, /Pretendard Variable|Pretendard|Noto Sans KR/);
    assert.equal(visualSystem.koreanReplacementGlyphs, 0);
    assert.equal(visualSystem.premiumStylesheet, true);
    assert.equal(visualSystem.approvedStylesheet, true);
    assert.equal(visualSystem.sidebarWidth, "258px");
    assert.equal(visualSystem.mainOffset, "258px");
    assert.equal(visualSystem.violetAccent, "#a58bff");
    assert.deepEqual(remoteFontRequests, [], "Korean UI fonts must not depend on Google Fonts network requests");
    checkpoint("premium typography and Korean text rendering verified");
    assert.equal(await page.locator(".main-nav a").count(), 9);
    assert.equal(await page.locator(".main-nav .nav-settings").count(), 1);
    assert.equal(await page.locator("#timelineEditor").count(), 1, "local timeline editor missing");
    await page.locator("#timelineMediaInput").setInputFiles({name:"not-a-video.txt",mimeType:"text/plain",buffer:Buffer.from("invalid")});
    assert.equal(await page.locator(".timeline-clip").count(), 0, "non-video file must be rejected");
    assert.match(await page.locator("#timelineStatus").textContent(), /동영상 형식이 아닙니다/);
    await page.locator("#timelineTitleInput").fill("First title");
    await page.locator("#timelineAddTitle").click();
    await page.locator("#timelineTitleInput").fill("Second title");
    await page.locator("#timelineAddTitle").click();
    assert.equal(await page.locator(".timeline-clip").count(), 2, "timeline title clips were not added");
    assert.equal(await page.locator("#timelineInspector").isVisible(), true);
    await page.locator(".timeline-clip-select").nth(1).click();
    await page.locator("#timelineMoveUp").click();
    assert.match(await page.locator(".timeline-clip-select").first().textContent(), /Second title/, "timeline reorder failed");
    await page.locator("#timelineIn").fill("1");
    await page.locator("#timelineOut").fill("4");
    await page.locator("#timelineApplyTrim").click();
    assert.match(await page.locator(".timeline-clip").first().textContent(), /1\.0s — 4\.0s/, "timeline trim values were not applied");
    const [timelineDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#timelineExport").click(),
    ]);
    const timelinePath = await timelineDownload.path();
    const editDecisionList = JSON.parse(fs.readFileSync(timelinePath, "utf8"));
    assert.equal(editDecisionList.format, "nexus-edit-decision-list");
    assert.equal(editDecisionList.rendered, false);
    assert.equal(editDecisionList.clips.length, 2);
    assert.equal(editDecisionList.clips[0].text, "Second title");
    assert.equal(await page.locator("#timelineTotalDuration").textContent(), "8.0s");
    await page.locator("#timelinePlaySelected").click();
    assert.match(await page.locator("#timelineStatus").textContent(), /타이틀 미리보기/);
    assert.equal(await page.locator("#timelineTitleOverlay").textContent(), "Second title");
    assert.equal(await page.locator("#timelineTitleOverlay").isVisible(), true);
    await page.locator("#timelineRemove").click();
    assert.equal(await page.locator(".timeline-clip").count(), 1, "timeline clip removal failed");
    assert.equal(await page.locator("#timelineTitleOverlay").textContent(), "First title");
    assert.equal(await page.locator("#timelineTitleOverlay").isVisible(), true, "remaining title preview did not recover");
    await page.locator("#timelineRemove").click();
    assert.equal(await page.locator(".timeline-clip").count(), 0, "timeline empty state recovery failed");
    assert.equal(await page.locator("#timelineTitleOverlay").isVisible(), false);
    assert.equal(await page.locator("#timelinePreviewEmpty").isVisible(), true);
    const destinations = ["home","trendList","trendRecommendations","productionForm","productionPipeline","reviewList","publishingOverview","analyticsHistory","queueDetails"];
    const navLinks = page.locator(".main-nav a");
    for (let index = 0; index < destinations.length; index++) {
      const link = navLinks.nth(index);
      assert.equal(await link.getAttribute("href"), "#" + destinations[index], "navigation destination mismatch: " + destinations[index]);
      assert.equal(await page.locator("#" + destinations[index]).count(), 1, "missing feature destination: " + destinations[index]);
      await link.click();
      assert.equal(await link.getAttribute("aria-current"), "page", "navigation active state missing: " + destinations[index]);
      assert.equal(await page.evaluate(() => location.hash), "#" + destinations[index]);
    }
    for (const label of ["대시보드","트렌드 탐색","콘텐츠 기획","AI 제작","영상 편집","검수·정책","게시 관리","성과 분석","작업 관리"]) assert.equal(await page.locator(".main-nav a").filter({ hasText: label }).count(), 1, "missing navigation item: " + label);
    assert.equal(await page.locator("#workspaceSearch").count(), 1);
    await page.keyboard.press("Control+k");
    assert.equal(await page.evaluate(() => document.activeElement.id), "workspaceSearch");
    await page.locator("#workspaceSearch").fill("수익성 평가");
    await page.keyboard.press("Enter");
    assert.match(await page.evaluate(() => document.activeElement.textContent), /수익성 평가/);
    await page.locator("#openSettingsNav").click();
    assert.equal(await page.locator("#settingsDialog").evaluate(node => node.open), true);
    await page.locator("#settingsDialog .dialog-close button").click();
    checkpoint("approved navigation, keyboard search and settings entry verified");
    assert.equal(await page.locator("#studio").count(), 1);
    assert.equal(await page.locator("#discovery").count(), 1);
    assert.equal(await page.locator("#review").count(), 1);
    assert.equal(await page.locator("#operations").count(), 1);
    assert.equal(await page.locator("#connection").getAttribute("role"), "status");

    await page.locator("#openSettings").click();
    await page.locator("#tokenInput").fill("nexus-ui-browser-smoke-token-2026-11-19-32chars");
    await page.locator("#saveToken").click();
    await page.locator("#settingsDialog").waitFor({ state: "hidden" });
    checkpoint("authenticated dashboard loaded");
    const workspaceSelector = page.locator("#workspaceSelector");
    assert.equal(await workspaceSelector.locator("option").count(), 2,
      "authenticated workspace membership was not loaded");
    const workspaceId = await workspaceSelector.locator("option").nth(1).getAttribute("value");
    assert.ok(workspaceId, "workspace option must have a stable ID");
    const scopedWorkspaceRequest = page.waitForRequest(request =>
      request.url().includes("/api/queue/stats") &&
      request.headers()["x-nexus-workspace-id"] === workspaceId
    );
    await workspaceSelector.selectOption(workspaceId);
    await scopedWorkspaceRequest;
    const legacyWorkspaceRequest = page.waitForRequest(request =>
      request.url().includes("/api/queue/stats") &&
      !request.headers()["x-nexus-workspace-id"]
    );
    await workspaceSelector.selectOption("");
    await legacyWorkspaceRequest;
    checkpoint("workspace selector and request-level workspace isolation verified");
    const authenticatedText = await page.locator("body").innerText();
    assert.equal([...authenticatedText].filter(character => character === "\uFFFD").length, 0);
    assert.equal(await page.locator("html").getAttribute("lang"), "ko");
    checkpoint("authenticated Korean content has no replacement glyphs");
    const liveApiChecks = await page.evaluate(async ({ token, workspaceId }) => {
      const paths = [
        "/api/brands",
        "/api/queue/stats",
        "/api/review/pending?limit=100",
        "/api/publishing/analytics-status",
      ];
      return Promise.all(paths.map(async path => {
        const headers = { "X-Review-Token": token };
        if (path === "/api/publishing/analytics-status") {
          headers["X-Nexus-Workspace-Id"] = workspaceId;
        }
        const response = await fetch(path, { headers });
        const body = await response.json();
        return { path, status: response.status, body };
      }));
    }, { token: "nexus-ui-browser-smoke-token-2026-11-19-32chars", workspaceId });
    assert.deepEqual(liveApiChecks.map(result => result.status), [200, 200, 200, 200]);
    assert.ok(Array.isArray(liveApiChecks[0].body.brands));
    assert.ok(Number.isFinite(Number(liveApiChecks[1].body.total)));
    assert.ok(Array.isArray(liveApiChecks[2].body.items));
    const reviewJob = liveApiChecks[2].body.items.find(item =>
      item.brand === "Browser Smoke" && item.topic === "A review-ready browser integration fixture"
    );
    assert.ok(reviewJob, "the real API must return the seeded review-ready job");
    assert.ok(liveApiChecks[3].body.youtube && liveApiChecks[3].body.tiktok);
    checkpoint("authenticated core API endpoints verified");
    const reviewCard = page.locator("#reviewList .review-card").filter({ hasText: reviewJob.job_id });
    await reviewCard.waitFor({ state: "visible" });
    await page.locator("#workspaceSearch").fill("Browser Smoke");
    await page.keyboard.press("Enter");
    assert.match(await page.evaluate(() => document.activeElement.textContent), /Browser Smoke/);
    checkpoint("global keyboard search finds live authenticated review content");
    await page.locator("#reviewSearch").fill("no-such-review-item");
    await page.waitForFunction(() => document.querySelector("#reviewSearchStatus").textContent.includes("0 / 1"));
    assert.equal(await reviewCard.isVisible(), false);
    await page.locator("#reviewSearch").fill("Browser Smoke");
    await page.waitForFunction(() => document.querySelector("#reviewSearchStatus").textContent.includes("1 / 1"));
    assert.equal(await reviewCard.isVisible(), true);
    page.once("dialog", async dialog => {
      assert.equal(dialog.type(), "prompt");
      await dialog.accept("실제 미디어와 정책 경고를 확인한 뒤 승인 메모를 기록했습니다.");
    });
    const approvalResponse = page.waitForResponse(response =>
      response.url().includes("/api/review/" + encodeURIComponent(reviewJob.job_id) + "/approve") &&
      response.request().method() === "POST"
    );
    await reviewCard.locator('button[data-action="approve"]').click();
    assert.equal((await waitForSignal(approvalResponse, "review approval response")).status(), 200);
    const approvalHistory = await page.evaluate(async ({ token, jobId }) => {
      const response = await fetch("/api/review/" + encodeURIComponent(jobId) + "/history", {
        headers: { "X-Review-Token": token },
      });
      return { status: response.status, body: await response.json() };
    }, {
      token: "nexus-ui-browser-smoke-token-2026-11-19-32chars",
      jobId: reviewJob.job_id,
    });
    assert.equal(approvalHistory.status, 200);
    assert.equal(approvalHistory.body.items.at(-1).decision, "approved");
    checkpoint("real review approval and audit history verified");
    await page.locator("#loadAnalyticsHistory").click();
    await waitForSignal(analyticsStarted, "analytics history request");
    assert.equal(await page.locator("#analyticsHistory").getAttribute("aria-busy"), "true");
    releaseAnalytics();
    await page.waitForFunction(() =>
      document.querySelector("#analyticsHistory").getAttribute("aria-busy") === "false" &&
      document.querySelector("#analyticsHistoryStatus").textContent.includes("기준 시각")
    );
    await analyticsHistoryResponsePromise;
    checkpoint("analytics history response " + JSON.stringify(analyticsHistoryResponse));
    assert.equal(
      await page.locator("#exportAnalyticsHistory").isDisabled(),
      false,
      "analytics export should be enabled; response=" + JSON.stringify(analyticsHistoryResponse)
    );
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
    checkpoint("real analytics pagination and CSV download verified");

    await workspaceSelector.selectOption(workspaceId);
    await page.evaluate(() => {
      const file = new File([new Uint8Array([0,1,2,3,4,5,6,7])], "timeline-smoke.mp4", {type:"video/mp4"});
      const url = URL.createObjectURL(file);
      const state = window.NexusLocalTimeline.state;
      state.clips = [
        {id:"clip-smoke",kind:"video",name:file.name,url,file,mimeType:file.type,sizeBytes:file.size,duration:5,inPoint:0,outPoint:5},
        {id:"title-smoke",kind:"title",name:"Render smoke",duration:5,inPoint:1,outPoint:4,text:"Render smoke"},
      ];
      state.selected="clip-smoke";
      window.NexusLocalTimeline.render();
    });
    await page.locator("#timelineAudioInput").setInputFiles([
      {name:"music-bed.wav",mimeType:"audio/wav",buffer:makeWavFixture()},
      {name:"voice-over.wav",mimeType:"audio/wav",buffer:makeWavFixture()},
    ]);
    await page.waitForFunction(() => document.querySelectorAll("#timelineAudioTracks .timeline-audio-track").length === 2);
    const audioRows=page.locator("#timelineAudioTracks .timeline-audio-track");
    await audioRows.nth(0).locator('input[aria-label="music-bed.wav Gain"]').fill("0.7");
    await audioRows.nth(0).locator('input[aria-label="music-bed.wav Gain"]').dispatchEvent("change");
    await audioRows.nth(1).locator('input[aria-label="voice-over.wav 시작(s)"]').fill("1.5");
    await audioRows.nth(1).locator('input[aria-label="voice-over.wav 시작(s)"]').dispatchEvent("change");
    await page.locator("#timelineSubmitRender").click();
    await page.waitForFunction(() => { const video=document.querySelector("#timelineServerPreview"); return video && !video.hidden && (video.getAttribute("src")||"").startsWith("blob:"); }, { timeout: 20000 }).catch(async error => { const debug=await page.locator("#timelineServerPreview").evaluate(el=>({hidden:el.hidden,src:el.getAttribute("src"),reviewHidden:document.querySelector("#timelineRenderReview")?.hidden,status:document.querySelector("#timelineStatus")?.textContent})); throw new Error(error.message+" · private preview state "+JSON.stringify(debug)); });
    await page.locator("#timelineRenderReview").waitFor({state:"visible",timeout:5000});
    assert.equal(uploadedTimelineAsset,true,"source media was not privately uploaded to the workspace");
    assert.equal(capturedTimelineEdl.schema,"nexus-edit-decision-list");
    assert.equal(capturedTimelineEdl.clips.filter(clip=>clip.type==="video").length,1);
    assert.equal(capturedTimelineEdl.clips.find(clip=>clip.type==="video").asset_id,"asset-smoke");
    assert.equal(capturedTimelineEdl.clips.find(clip=>clip.type==="title").text,"Render smoke");
    assert.equal(capturedTimelineEdl.audio_tracks.length,2,"two independent audio tracks must be submitted");
    assert.equal(capturedTimelineEdl.audio_tracks[0].gain,0.7);
    assert.equal(capturedTimelineEdl.audio_tracks[1].start_ms,1500);
    assert.equal(await page.locator("#timelineMediaShelf .timeline-media-card").count(),2,"local media shelf should show the uploaded video and title overlay");
    assert.equal(await page.locator("#timelineVisualTrack .timeline-visual-lane").count(),3,"visual timeline should render video, title and audio lanes");
    assert.equal(await page.locator("#timelineVisualTrack .timeline-segment.is-video").count(),1);
    assert.equal(await page.locator("#timelineVisualTrack .timeline-segment.is-title").count(),1);
    assert.equal(await page.locator("#timelineVisualDuration").textContent(),"5.0s");
    const initialTimelineWidth=await page.locator("#timelineVisualTrack").evaluate(el=>el.getBoundingClientRect().width);
    await page.locator("#timelineZoomIn").click();
    assert.equal(await page.locator("#timelineZoomValue").textContent(),"125%");
    const zoomedTimelineWidth=await page.locator("#timelineVisualTrack").evaluate(el=>el.getBoundingClientRect().width);
    assert.ok(zoomedTimelineWidth>initialTimelineWidth,"timeline zoom should expand the time canvas");
    await page.locator("#timelineZoomLevel").fill("2.5");
    assert.equal(await page.locator("#timelineZoomValue").textContent(),"250%");
    await page.locator("#timelineZoomFit").click();
    assert.equal(await page.locator("#timelineZoomValue").textContent(),"100%");
    assert.equal(await page.locator("#timelineScrollLeft").isVisible(),true);
    assert.equal(await page.locator("#timelineScrollRight").isVisible(),true);
    await page.locator("#timelineApproveRender").scrollIntoViewIfNeeded();
    await page.locator("#timelineApproveRender").click();
    await page.waitForFunction(()=>document.querySelector("#timelineRenderReview").hidden===true);
    assert.equal(capturedTimelineDecision.decision,"approved");

    await page.locator("#timelineMediaFilter").fill("Render smoke");
    assert.equal(await page.locator("#timelineMediaShelf .timeline-media-card").count(),1,"media shelf filter should narrow the asset board");
    await page.locator("#timelineMediaFilter").fill("");
    await page.locator("#timelineMediaShelf .timeline-media-card").first().click();
    assert.equal(await page.locator("#timelineInspector").isVisible(),true,"selecting a media card should open the clip detail inspector");
    assert.match(await page.locator("#timelineSelectedMeta").textContent(),/검사 완료/,"detail inspector should show server scan status");
    assert.equal(await page.locator("#timelineServerPreview").isVisible(),true,"rendered review artifact preview missing");
    assert.match(await page.locator("#timelineServerPreview").getAttribute("src"),/^blob:/,"private artifact should be fetched as an authenticated browser blob");
    checkpoint("authenticated workspace upload → EDL validation → render status → private artifact preview → human review decision verified (API contract mock)");


    failQueueStats = true;
    await page.locator("#refreshAll").click();
    await page.waitForFunction(() =>
      document.querySelector("#connection").textContent.includes("API 부분 연결")
    );
    assert.match(await page.locator("#toast").textContent(), /일부 데이터 갱신 실패/);
    checkpoint("partial API failure handling verified");
    failQueueStats = false;

    await page.reload({ waitUntil: "networkidle" });
    await page.evaluate(() => { window.scrollTo(0, 0); document.activeElement?.blur?.(); });
    await page.locator("body").click({ position: { x: 1, y: 1 } });
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains("skip-link")), true);
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.activeElement.id), "home");

    for (const section of ["trendList", "trendRecommendations", "productionForm", "productionPipeline", "reviewList", "publishingOverview", "analyticsHistory", "queueDetails"]) {
      const link = page.locator('.main-nav a[href="#' + section + '"]').first();
      await link.click();
      assert.equal(await link.getAttribute("aria-current"), "page");
      assert.equal(await page.evaluate(() => location.hash), "#" + section);
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
      const targets = await page.locator(".main-nav a, .main-nav button").evaluateAll(links =>
        links.map(link => {
          const rect = link.getBoundingClientRect();
          return { width: rect.width, height: rect.height };
        })
      );
      assert.ok(targets.every(rect => rect.width >= 48 && rect.height >= 48),
        "compact navigation touch targets must be at least 48px");
    }

    await page.screenshot({ path: "artifacts/nexus-dashboard-mobile.png", fullPage: true });
    checkpoint("responsive desktop/mobile and keyboard checks verified");
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
