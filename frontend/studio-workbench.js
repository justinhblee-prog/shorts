(() => {
  const $ = id => document.getElementById(id);
  const textOf = el => (el?.textContent || "").replace(/\s+/g, " ").trim();
  const number = el => {
    const parsed = Number(textOf(el).replace(/[^0-9.-]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  };
  function update() {
    const queued = number($("metricQueued"));
    const running = number($("metricRunning"));
    const review = number($("metricReview"));
    const approved = $("approvedList")?.querySelectorAll(".review-card").length ?? 0;
    const trendList = $("trendList");
    const trends = trendList && !trendList.querySelector(".empty-state") ? (trendList.querySelectorAll(".trend-card,.trend-item,.data-item").length || trendList.children.length) : null;
    const set = (id, value) => { if ($(id)) $(id).textContent = value == null ? "—" : value.toLocaleString(); };
    set("stageDiscover", trends);
    set("stageCreate", queued == null || running == null ? null : queued + running);
    set("stageReview", review);
    set("stageMeasure", approved);
    set("railQueued", queued);
    set("railRunning", running);
    set("railReview", review);
    const active = review > 0 ? 2 : (running > 0 || queued > 0 ? 1 : 0);
    document.querySelectorAll(".stage-node").forEach((node,index)=>node.classList.toggle("is-active",index===active));
    const note=$("studioStageNote");
    if(note)note.textContent=queued==null||review==null
      ?"인증 후 실제 API 데이터를 표시합니다."
      :"API 실측 · 대기 "+queued+" · 실행 "+(running??0)+" · 검수 "+review+" · 승인 콘텐츠 "+approved;
    const spotlight=$("studioMediaSpotlight");
    const first=document.querySelector("#reviewList video.timeline-render-preview");
    const source=first?.currentSrc||first?.src||"";
    if(spotlight&&first&&spotlight.dataset.source!==source){
      const card=first.closest(".review-card");
      const video=first.cloneNode(true);video.className="spotlight-video";video.controls=true;video.playsInline=true;
      const meta=document.createElement("div");meta.className="spotlight-meta";
      const title=document.createElement("b");title.textContent=card?.querySelector("h4")?.textContent||"검수 대기 콘텐츠";
      const small=document.createElement("small");small.textContent="실제 검수 대기 산출물 · 사람의 승인 필요";
      meta.append(title,small);spotlight.replaceChildren(video,meta);
      const link=document.createElement("a");link.className="media-open";link.href="#reviewList";link.textContent="전체 검수 항목 열기 ↗";spotlight.append(link);
      spotlight.dataset.source=source;
    }else if(spotlight&&!first&&!spotlight.dataset.empty){
      spotlight.innerHTML='<div class="media-placeholder"><span>▶</span><b>검수 대기 영상이 여기에 표시됩니다.</b><small>실제 검수 미디어가 있을 때만 미리보기를 표시합니다.</small></div>';
      delete spotlight.dataset.source;spotlight.dataset.empty="1";
    }else if(spotlight&&first){delete spotlight.dataset.empty;}
  }
  const targets=["metricQueued","metricRunning","metricReview","trendList","reviewList","approvedList"].map($).filter(Boolean);
  const observer=new MutationObserver(update);
  targets.forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true}));
  window.addEventListener("nexus:auth-changed",update);
  window.addEventListener("nexus:workspace-changed",update);
  window.addEventListener("load",update);
  update();
})();
