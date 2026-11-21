(() => {
  const $ = id => document.getElementById(id);
  const textOf = el => (el?.textContent || "").replace(/\s+/g, " ").trim();
  const numeric = id => {
    const value = textOf($(id));
    const parsed = Number(value.replace(/[^0-9.-]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  };
  function updateWorkbench() {
    const queued = numeric("metricQueued");
    const running = numeric("metricRunning");
    const review = numeric("metricReview");
    const approved = $("approvedList")?.querySelectorAll(".review-card").length ?? 0;
    const set = (id, value) => { if ($(id)) $(id).textContent = value == null ? "—" : value.toLocaleString(); };
    set("stageDiscover", textOf($("trendList")) && !$("trendList").querySelector(".empty-state") ? $("trendList").querySelectorAll(".data-item").length : null);
    set("stageCreate", queued == null || running == null ? null : queued + running);
    set("stageReview", review);
    set("stageMeasure", approved);
    set("railQueued", queued);
    set("railRunning", running);
    set("railReview", review);
    const active = review > 0 ? 2 : running > 0 || queued > 0 ? 1 : 0;
    document.querySelectorAll(".stage-node").forEach((node, index) => node.classList.toggle("is-active", index === active));
    const note = $("studioStageNote");
    if (note) note.textContent = queued == null || review == null
      ? "인증 후 실제 큐와 검수 데이터로 상태를 표시합니다."
      : "실제 API 기준 · 대기 " + queued + " · 실행 " + (running ?? 0) + " · 검수 " + review + " · 승인 완료 " + approved;
    const spotlight = $("studioMediaSpotlight");
    const first = document.querySelector("#reviewList .review-media-preview video");
    if (spotlight && first && !spotlight.dataset.loaded) {
      const card = first.closest(".review-card");
      const title = card?.querySelector("h4")?.textContent || "검수 대기 콘텐츠";
      const video = first.cloneNode(true);
      video.className = "spotlight-video";
      video.controls = true;
      const meta = document.createElement("div");
      meta.className = "spotlight-meta";
      const strong = document.createElement("b"); strong.textContent = title;
      const small = document.createElement("small"); small.textContent = "실제 검수 대기 산출물 · 사람의 승인 필요";
      meta.append(strong, small);
      spotlight.replaceChildren(video, meta);
      const link = document.createElement("a"); link.className = "spotlight-open"; link.href = "#review"; link.textContent = "전체 검수 항목 열기 ↗";
      spotlight.append(link);
      spotlight.dataset.loaded = "1";
    } else if (spotlight && !first && !spotlight.dataset.loaded) {
      spotlight.innerHTML = '<div class="media-placeholder"><span>▶</span><b>검수 가능한 영상이 여기에 표시됩니다.</b><small>실제 HTTPS video artifact가 존재할 때만 미리보기를 표시합니다.</small></div>';
    }
  }
  const search = $("globalSearch"), results = $("globalSearchResults");
  function runSearch(value) {
    if (!results) return;
    const query = value.trim().toLocaleLowerCase();
    if (!query) { results.hidden = true; results.replaceChildren(); return; }
    const candidates = [...document.querySelectorAll("main h2,main h3,main h4,main .review-card,main .data-item,main .metric-card,main .pipeline-step")]
      .filter(el => !el.closest("#globalSearchResults"));
    const matches = candidates.filter(el => textOf(el).toLocaleLowerCase().includes(query)).slice(0, 8);
    results.replaceChildren();
    if (!matches.length) {
      const empty = document.createElement("div"); empty.className = "global-search-empty"; empty.textContent = "일치하는 작업이나 콘텐츠가 없습니다."; results.append(empty);
    } else matches.forEach(el => {
      const button = document.createElement("button"); button.type = "button";
      const title = document.createElement("b"); title.textContent = textOf(el).slice(0, 100) || "항목";
      const section = el.closest("section"); const small = document.createElement("small");
      small.textContent = section?.querySelector("h2")?.textContent || section?.getAttribute("aria-label") || "NEXUS STUDIO";
      button.append(title, small);
      button.addEventListener("click", () => { el.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"center"}); el.classList.add("search-focus"); setTimeout(() => el.classList.remove("search-focus"), 1200); results.hidden = true; search.value = ""; });
      results.append(button);
    });
    results.hidden = false;
  }
  if (search && results) {
    search.addEventListener("input", () => runSearch(search.value));
    search.addEventListener("keydown", event => { if (event.key === "Escape") { results.hidden = true; search.blur(); } if (event.key === "Enter" && !results.hidden) results.querySelector("button")?.click(); });
    document.addEventListener("click", event => { if (!event.target.closest(".global-command")) results.hidden = true; });
    document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); search.focus(); } });
  }
  const reviewList = $("reviewList"), approvedList = $("approvedList"), trendList = $("trendList");
  [reviewList, approvedList, trendList].forEach(target => {
    if (target) new MutationObserver(() => { updateWorkbench(); if (search?.value) runSearch(search.value); }).observe(target, {childList:true,subtree:true});
  });
  document.addEventListener("DOMContentLoaded", updateWorkbench);
  window.addEventListener("load", updateWorkbench);
  const refresh = $("refreshAll");
  refresh?.addEventListener("click", () => setTimeout(updateWorkbench, 400));
  updateWorkbench();
  setInterval(updateWorkbench, 1800);
})();
