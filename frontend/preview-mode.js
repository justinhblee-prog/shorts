(() => {
  "use strict";
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
})();