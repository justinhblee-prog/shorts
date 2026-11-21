(() => {
  "use strict";
  // This safety overlay is only for the isolated Vercel preview host. Keep local/CI
  // browser tests connected to their seeded test API and normal navigation semantics.
  if (!location.hostname.startsWith("nexus-studio-pro-ui-preview") || !location.hostname.endsWith(".vercel.app")) return;
  document.documentElement.classList.add("nexus-visual-preview");
  const banner=document.createElement("aside");
  banner.className="nexus-preview-banner";
  banner.setAttribute("role","status");
  banner.innerHTML='<span class="preview-pulse"></span><strong>화면 상시 미리보기</strong><span>검토용 데모 화면입니다 · 운영 API/실제 계정 데이터와 분리되어 있습니다.</span><span class="preview-version">LIVE UI PREVIEW</span>';
  document.body.insertBefore(banner,document.body.firstChild);
  const style=document.createElement("style");
  style.textContent=`
    .nexus-preview-banner{position:fixed;inset:0 0 auto 0;z-index:100000;min-height:42px;box-sizing:border-box;display:flex;align-items:center;gap:11px;padding:8px 18px;background:linear-gradient(90deg,#182744,#29224b);border-bottom:1px solid #6476a6;color:#edf2ff;font:600 12px/1.4 system-ui,sans-serif;box-shadow:0 6px 24px #0005}
    .nexus-preview-banner>span:nth-of-type(1){color:#b8c5dc;font-weight:450}
    .preview-pulse{width:8px;height:8px;border-radius:50%;background:#71e2c1;box-shadow:0 0 12px #71e2c1;flex:0 0 auto}
    .preview-version{margin-left:auto;color:#b8aaff;font:10px/1.2 monospace;letter-spacing:.12em}
    .nexus-visual-preview .topbar{top:42px!important}
    .nexus-visual-preview main{padding-top:82px!important}
    .nexus-visual-preview .footer{position:relative}
    @media(max-width:760px){.nexus-preview-banner{min-height:42px;padding:7px 10px;gap:7px;font-size:10px}.nexus-preview-banner>span:nth-of-type(1){max-width:54vw}.preview-version{font-size:8px}.nexus-visual-preview .topbar{top:42px!important}.nexus-visual-preview main{padding-top:18px!important}}
    @media(max-width:390px){.nexus-preview-banner{font-size:9px}.nexus-preview-banner>span:nth-of-type(1){max-width:48vw}}
  `;
  document.head.appendChild(style);
  const status=document.getElementById("connection");
  if(status){status.innerHTML='<i></i> 화면 미리보기 · API 미연결';status.title="이 주소는 UI 검토용입니다. 실제 운영 데이터나 API 작업은 수행하지 않습니다.";}
  const statusObserver=new MutationObserver(()=>{
    const node=document.getElementById("connection");
    if(node&&node.textContent!=="화면 미리보기 · API 미연결"){
      node.innerHTML='<i></i> 화면 미리보기 · API 미연결';
      node.title="이 주소는 UI 검토용입니다. 실제 운영 데이터나 API 작업은 수행하지 않습니다.";
    }
  });
  if(status)statusObserver.observe(status,{childList:true,subtree:true,characterData:true});
  for(const id of ["openSettings","openSettingsNav"]){
    const button=document.getElementById(id);
    if(button){button.disabled=true;button.title="미리보기에서는 운영 API 인증을 설정할 수 없습니다.";}
  }
  for(const id of ["productionForm","trendForm","competitorForm","opportunityForm","scheduleForm","ledgerForm"]){
    const form=document.getElementById(id);
    if(form){for(const button of form.querySelectorAll('button[type="submit"],button:not([type])')){button.disabled=true;button.title="미리보기 전용 화면에서는 실제 작업을 등록하지 않습니다.";} }
  }
  const note=document.createElement("p");
  note.className="nexus-preview-inline-note";
  note.textContent="미리보기 모드: 메뉴·레이아웃·반응형 화면을 확인할 수 있습니다. 실제 제작/게시/재무 작업은 실행되지 않습니다.";
  const main=document.querySelector("main");
  if(main)main.insertBefore(note,main.firstChild);
  const noteStyle=document.createElement("style");
  noteStyle.textContent=".nexus-preview-inline-note{margin:0 0 16px;padding:10px 14px;border:1px solid #4b5d82;border-radius:10px;background:#111e32;color:#b9c8e5;font-size:11px;}";
  document.head.appendChild(noteStyle);

  const navLinks=[...document.querySelectorAll('header a[href^="#"]')].filter(a=>document.querySelector(a.getAttribute("href")));
  const navSections=navLinks.map(a=>({a,el:document.querySelector(a.getAttribute("href"))})).filter(x=>x.el);
  const markActive=(id)=>navSections.forEach(({a,el})=>{const active=el.id===id;a.classList.toggle("preview-nav-active",active);if(active)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");});
  if("IntersectionObserver" in window){
    const observer=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];if(visible)markActive(visible.target.id);},{rootMargin:"-18% 0px -68% 0px",threshold:[0,.15,.35,.6]});
    navSections.forEach(({el})=>observer.observe(el));
  }
  navSections.forEach(({a,el})=>a.addEventListener("click",()=>markActive(el.id)));
  if(navSections.length)markActive(navSections[0].el.id);
  const feedback=document.createElement("section");
  feedback.className="nexus-feedback";
  feedback.innerHTML='<button type="button" class="nexus-feedback-toggle" aria-expanded="false">✎ 화면 피드백</button><div class="nexus-feedback-body" hidden><label for="nexusFeedbackText">수정할 화면과 내용을 적어주세요</label><textarea id="nexusFeedbackText" rows="4" placeholder="예: 콘텐츠 기획 화면에서 카드 간격을 줄이고 필터를 위쪽으로 이동해주세요."></textarea><div class="nexus-feedback-actions"><button type="button" class="nexus-feedback-copy">피드백 복사</button><span class="nexus-feedback-status" role="status" aria-live="polite"></span></div><p>복사한 내용을 이 대화에 붙여 보내주시면 해당 화면부터 반영하겠습니다.</p></div>';
  document.body.appendChild(feedback);
  const feedbackStyle=document.createElement("style");
  feedbackStyle.textContent=`
    header a.preview-nav-active{background:rgba(128,111,255,.17)!important;color:#fff!important;box-shadow:inset 2px 0 #a99aff}
    .nexus-feedback{position:fixed;z-index:99998;right:20px;bottom:20px;width:min(350px,calc(100vw - 32px));font:12px/1.5 system-ui,sans-serif;color:#e8edff}
    .nexus-feedback-toggle,.nexus-feedback-copy{border:1px solid #8273dd;border-radius:12px;background:#28224c;color:#fff;padding:11px 15px;font-weight:700;box-shadow:0 8px 28px #0007;cursor:pointer}
    .nexus-feedback-toggle{display:block;margin-left:auto}
    .nexus-feedback-body{margin-top:9px;padding:14px;border:1px solid #59658b;border-radius:14px;background:#111a2c;box-shadow:0 12px 40px #0009}
    .nexus-feedback-body label{display:block;margin-bottom:7px;font-weight:700}
    .nexus-feedback-body textarea{box-sizing:border-box;width:100%;resize:vertical;border:1px solid #465578;border-radius:9px;background:#0a1220;color:#fff;padding:10px;font:12px/1.5 system-ui,sans-serif}
    .nexus-feedback-actions{display:flex;align-items:center;gap:10px;margin-top:9px}
    .nexus-feedback-copy{padding:8px 12px}
    .nexus-feedback-status,.nexus-feedback-body p{color:#aebbd8;font-size:10px}
    .nexus-feedback-body p{margin:9px 0 0}
    @media(max-width:600px){.nexus-feedback{right:12px;bottom:12px;width:min(330px,calc(100vw - 24px))}.nexus-feedback-toggle{padding:10px 13px}}
  `;
  document.head.appendChild(feedbackStyle);
  const toggle=feedback.querySelector(".nexus-feedback-toggle");
  const body=feedback.querySelector(".nexus-feedback-body");
  toggle.addEventListener("click",()=>{const open=body.hidden;body.hidden=!open;toggle.setAttribute("aria-expanded",String(open));toggle.textContent=open?"× 피드백 닫기":"✎ 화면 피드백";});
  feedback.querySelector(".nexus-feedback-copy").addEventListener("click",async()=>{
    const value=feedback.querySelector("#nexusFeedbackText").value.trim();
    const status=feedback.querySelector(".nexus-feedback-status");
    if(!value){status.textContent="먼저 수정 의견을 입력해주세요.";return;}
    const section=navSections.find(({el})=>el.getBoundingClientRect().top<window.innerHeight&&el.getBoundingClientRect().bottom>0);
    const label=section?.a.innerText.trim().replace(/\s+/g," ")||"현재 화면";
    const note="[NEXUS 화면 피드백] "+label+"\n"+value;
    try{await navigator.clipboard.writeText(note);status.textContent="복사했습니다. 이 대화에 붙여넣어 주세요.";}
    catch{const area=feedback.querySelector("#nexusFeedbackText");area.value=note;area.focus();area.select();status.textContent="텍스트를 선택했습니다. 복사해 주세요.";}
  });
})();
