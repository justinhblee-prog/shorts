(() => {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let reviewer = "operator";
  let brands = [];
  let toastTimer;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const money = (n,c="USD") => new Intl.NumberFormat("en-US",{style:"currency",currency:c,maximumFractionDigits:2}).format(Number(n||0));
  function toast(message){$("toast").textContent=message;$("toast").classList.add("show");clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").classList.remove("show"),2800);}
  function msg(id,text,error=false){const el=$(id);el.textContent=text;el.classList.toggle("error",!!error);}
  async function api(path,options={}){
    const headers={"Content-Type":"application/json",...(options.headers||{})};
    if(token) headers["X-Review-Token"]=token;
    const response=await fetch(path,{...options,headers});
    const raw=await response.text();let data={};
    try{data=raw?JSON.parse(raw):{};}catch{data={detail:raw};}
    if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data));
    return data;
  }
  function setConnection(connected,label){$("connection").classList.toggle("connected",connected);$("connection").innerHTML='<i></i> '+esc(label);}
  function populateBrandSelects(){
    const opts=brands.filter(b=>b.active).map(b=>'<option value="'+esc(b.slug)+'">'+esc(b.name)+'</option>').join("");
    ["brandSelect","scheduleBrand","ledgerBrand"].forEach(id=>$(id).innerHTML=opts||'<option value="">브랜드 없음</option>');
    $("metricBrands").textContent=brands.filter(b=>b.active).length;
  }
  async function loadBrands(){
    const data=await api("/api/brands");brands=data.brands||[];populateBrandSelects();
  }
  async function loadMetrics(){
    const [q,r,f]=await Promise.all([api("/api/queue/stats"),api("/api/review/pending?limit=200"),api("/api/finance/report?currency=USD")]);
    const queued=Number(q.queued||0)+Number(q.failed_retriable||0);
    $("metricQueued").textContent=queued.toLocaleString();
    $("metricRunning").textContent="실행 중 "+Number(q.running||0).toLocaleString();
    $("metricReview").textContent=(r.items||[]).length.toLocaleString();
    $("reviewCount").textContent=(r.items||[]).length+" ITEMS";
    const revenue=Number(f.revenue||0),cost=Number(f.costs||f.cost||0),net=Number(f.net_profit??(revenue-cost));
    $("metricRevenue").textContent=money(revenue);
    setConnection(true,"API 연결됨");
  }

  async function loadFinance(){
    const currency=$("ledgerCurrency").value||"USD";
    const data=await api("/api/finance/report?currency="+encodeURIComponent(currency));
    $("financeRevenue").textContent=money(data.revenue,currency);
    $("financeCosts").textContent=money(data.costs,currency);
    $("financeNet").textContent=money(data.net,currency);
  }
  async function loadReviews(){
    const data=await api("/api/review/pending?limit=100");
    const items=data.items||[];$("reviewCount").textContent=items.length+" ITEMS";
    $("metricReview").textContent=items.length;
    $("reviewList").innerHTML=items.length?items.map(item=>{
      const video=(item.artifacts||[]).find(a=>a.artifact_type==="video");
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · '+esc(item.current_stage||item.status)+'</p><div class="review-meta">JOB '+esc(item.job_id)+' · '+esc(item.updated_at||"")+'</div>'+(video?'<p><a target="_blank" rel="noopener" href="'+esc(video.artifact_url)+'">렌더링 영상 열기 ↗</a></p>':'')+'<div class="inline-message" id="stage-'+esc(item.job_id)+'"></div></div><div class="review-actions"><button class="button button-quiet" data-action="stage" data-id="'+esc(item.job_id)+'">미디어 스테이징</button><button class="button button-primary" data-action="approve" data-id="'+esc(item.job_id)+'">승인</button><button class="button button-outline" data-action="revision" data-id="'+esc(item.job_id)+'">수정 요청</button><button class="button button-quiet" data-action="reject" data-id="'+esc(item.job_id)+'">반려</button></div></article>';
    }).join(""):'<div class="empty-state">현재 검수 대기 콘텐츠가 없습니다.</div>';
  }

  async function loadApproved(){
    const data=await api("/api/review/approved?limit=100");
    const items=data.items||[];
    $("approvedList").innerHTML=items.length?items.map(item=>{
      const video=(item.artifacts||[]).find(a=>a.artifact_type==="video");
      const uncertain=!!item.upload_reconciliation_required;
      const status=item.upload_status||"not_uploaded";
      const lateIds=(item.upload_events||[]).filter(event=>event.event_type==="late_remote_success"&&event.video_id).map(event=>event.video_id);
      const lateIdSummary=lateIds.length?'<p>늦게 확인된 영상 ID: '+lateIds.map(esc).join(" · ")+'</p>':"";
      const existingIdSummary=item.upload_video_id?'<p>현재 기록된 영상 ID: '+esc(item.upload_video_id)+'</p>':"";
      const action=status==="late_success_review_required"
        ? '<button class="button button-outline" data-resolve-late-id="'+esc(item.job_id)+'">늦은 업로드 결과 확정</button>'
        : (uncertain
          ? '<button class="button button-outline" data-reconcile-id="'+esc(item.job_id)+'">업로드 결과 대조</button>'
          : (status==="uploading"
            ? '<button class="button button-quiet" disabled>업로드 진행 중 · 대기</button>'
            : '<button class="button button-primary" data-upload-id="'+esc(item.job_id)+'">비공개 업로드</button>'));
      const statusText=status==="late_success_review_required"?"늦은 업로드 성공 · 운영자 확인 필요":(uncertain?"업로드 결과 확인 필요":(status==="uploading"?"업로드 진행 중":(status==="failed"?"이전 업로드 실패 · 재시도 가능":(status==="uploaded"?"업로드 완료":"업로드 대기"))));
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · 승인 완료 · '+esc(statusText)+'</p><div class="review-meta">JOB '+esc(item.job_id)+'</div>'+(video?'<p><a target="_blank" rel="noopener" href="'+esc(video.artifact_url)+'">원본 영상 열기 ↗</a></p>':'')+existingIdSummary+lateIdSummary+'<div class="inline-message" id="upload-'+esc(item.job_id)+'"></div></div><div class="review-actions">'+action+'</div></article>';
    }).join(""):'<div class="empty-state">승인 완료 후 업로드 대기 중인 콘텐츠가 없습니다.</div>';
  }
  async function loadTrends(){
    const data=await api("/api/trends?limit=12");
    $("trendList").innerHTML=(data.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.title||x.query||"Untitled signal")+'</b><small>'+esc(x.region||"")+' · '+esc(x.source||"")+' · '+esc(x.published_at||x.collected_at||"")+'</small></div>').join("")||'<div class="empty-state">저장된 트렌드 신호가 없습니다.</div>';
  }
  async function loadSchedules(){
    const [data,outbox]=await Promise.all([api("/api/schedules"),api("/api/schedules/outbox")]);
    const schedules=(data.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.name)+' · '+(x.active?"활성":"중지")+'</b><small>'+esc(x.payload.brand)+' · '+esc(x.payload.region)+' · 다음 실행 '+esc(x.next_run_at)+'</small></div>').join("")||'<div class="empty-state">등록된 예약이 없습니다.</div>';
    const dispatches=(outbox.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.status)+' · '+esc(x.schedule_id)+'</b><small>'+esc(x.scheduled_for)+' · attempts '+x.attempts+(x.last_error?' · '+esc(x.last_error):'')+'</small></div>').join("");
    $("scheduleList").innerHTML='<div class="notice">Outbox pending/retry: '+Number(outbox.pending_retries||0)+' · dispatched: '+Number((outbox.counts||{}).dispatched||0)+'</div>'+schedules+'<h4>예약 실행 복구 로그</h4>'+(dispatches||'<div class="empty-state">예약 실행 이력이 없습니다.</div>');
  }
  async function loadInsights(){
    const data=await api("/api/performance/insights");
    const brands=(data.brands||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+Number(x.view_delta||0).toLocaleString()+' views (snapshot delta)</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+' · 미측정 '+x.unmeasured_videos+' · '+esc((x.recommendations||[]).map(r=>r.action).join(" / "))+'</small></div>').join("");
    const regions=(data.regions||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+Number(x.view_delta||0).toLocaleString()+' views</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+'</small></div>').join("");
    const videos=(data.videos||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic)+'</b><small>'+esc(x.measurement_status)+' · snapshots '+x.snapshot_count+(x.view_delta===undefined?"":" · Δ "+Number(x.view_delta).toLocaleString())+'</small></div>').join("");
    const finance=(data.financial||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+esc(x.currency)+' · net '+money(x.net,x.currency)+'</b><small>매출 '+money(x.revenue,x.currency)+' · 비용 '+money(x.costs,x.currency)+' · '+x.entries+'건</small></div>').join("");
    $("insightList").innerHTML='<h4>브랜드 성과</h4>'+(brands||'<div class="empty-state">업로드된 영상 데이터가 없습니다.</div>')+'<h4>지역별 성과</h4>'+(regions||'<div class="empty-state">지역별 데이터가 없습니다.</div>')+'<h4>영상별 측정 상태</h4>'+(videos||'<div class="empty-state">영상 측정 데이터가 없습니다.</div>')+'<h4>실제 기록 금융 데이터 (통화별)</h4>'+(finance||'<div class="empty-state">기록된 금융 데이터가 없습니다.</div>')+'<div class="notice">'+(data.limitations||[]).map(esc).join(" · ")+'</div>';
  }

  async function loadPreflight(){
    const data=await api("/api/preflight");
    const labels={operator_auth:"운영자 인증",script_generation:"AI 대본",voice_generation:"AI 음성",video_rendering:"영상 렌더링",artifact_staging:"렌더링 파일 스테이징",youtube_upload:"YouTube OAuth",youtube_data_api:"YouTube 데이터 API",media_directory:"미디어 저장소"};
    $("preflightList").innerHTML=Object.entries(data.checks||{}).map(([key,value])=>'<div class="data-item"><b>'+esc(labels[key]||key)+' · <span class="'+(value.configured?"ready-text":"missing-text")+'">'+(value.configured?"설정 확인":"설정 누락")+'</span></b><small>'+esc((value.missing||[]).join(", ")||"필수 설정값 존재")+'</small></div>').join("")+'<div class="notice"><b>'+(data.capabilities.end_to_end_configured?"필수 설정값 구성 완료":"외부 연동 설정이 더 필요합니다")+'</b><span>'+esc(data.note)+'</span></div>';
  }
  async function loadQueue(){
    const [q,w]=await Promise.all([api("/api/queue/stats"),api("/api/workers")]);
    $("queueDetails").innerHTML='<div class="data-item"><b>Queue status</b><small>'+esc(JSON.stringify(q))+'</small></div>'+(w.workers||[]).map(x=>'<div class="data-item"><b>'+esc(x.worker_id)+' · '+esc(x.status)+'</b><small>'+esc(x.hostname||"")+' · '+esc(x.last_seen_at||"")+'</small></div>').join("");
  }
  async function refreshAll(){
    if(!token){setConnection(false,"인증 필요");return;}
    try{
      await Promise.all([loadMetrics(),loadFinance(),loadReviews(),loadApproved(),loadTrends(),loadSchedules(),loadInsights(),loadQueue(),loadPreflight()]);
      toast("운영 데이터 갱신 완료");
    }catch(e){setConnection(false,"인증·API 확인 필요");toast(e.message);}
  }
  function requireToken(){if(!token){$("settingsDialog").showModal();return false;}return true;}
  $("openSettings").addEventListener("click",()=>$("settingsDialog").showModal());
  $("saveToken").addEventListener("click",async()=>{
    token=$("tokenInput").value.trim();reviewer=$("reviewerInput").value.trim()||"operator";
    try{await api("/api/queue/stats");$("settingsDialog").close();msg("tokenMessage","인증 성공");await refreshAll();}
    catch(e){token="";msg("tokenMessage",e.message,true);}
  });
  $("clearToken").addEventListener("click",()=>{token="";$("tokenInput").value="";setConnection(false,"인증 필요");msg("tokenMessage","토큰이 메모리에서 초기화되었습니다.");});
  $("refreshAll").addEventListener("click",refreshAll);
  $("loadReviews").addEventListener("click",()=>loadReviews().catch(e=>toast(e.message)));
  $("loadSchedules").addEventListener("click",()=>loadSchedules().catch(e=>toast(e.message)));
  $("loadInsights").addEventListener("click",()=>loadInsights().catch(e=>toast(e.message)));
  $("loadPreflight").addEventListener("click",()=>loadPreflight().catch(e=>toast(e.message)));
  $("productionForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const result=await api("/api/production/jobs",{method:"POST",body:JSON.stringify({brand:$("brandSelect").value,region:$("regionSelect").value,language:$("languageSelect").value,topic:$("topicInput").value.trim()})});msg("productionMessage","작업 등록 완료 · "+result.job.id);$("topicInput").value="";await refreshAll();}
    catch(err){msg("productionMessage",err.message,true);}
  });
  $("trendForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const r=await api("/api/trends/collect",{method:"POST",body:JSON.stringify({region:$("trendRegion").value,query:$("trendQuery").value.trim(),limit:Number($("trendLimit").value),include_hacker_news:true})});msg("trendList","수집 완료 · "+(r.stored??r.count??"저장 결과 확인"));await loadTrends();}
    catch(err){toast(err.message);}
  });
  $("competitorForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const r=await api("/api/competitors/search?q="+encodeURIComponent($("competitorQuery").value.trim()));$("competitorList").innerHTML=(r.channels||r.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.title||x.name||x.channel_title||x.channel_id)+'</b><small>'+esc(x.custom_url||x.channel_id||"")+' · '+esc(x.subscriber_count??"subscriber count hidden")+'</small></div>').join("")||'<div class="empty-state">검색 결과가 없습니다.</div>';}
    catch(err){toast(err.message);}
  });
  $("opportunityForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    const num=id=>Number($(id).value);
    const body={title:$("oppTitle").value,currency:$("oppCurrency").value,forecast_source:$("forecastSource").value,forecast_views_low:num("viewsLow"),forecast_views_high:num("viewsHigh"),rpm_low:num("rpmLow"),rpm_high:num("rpmHigh"),cost_low:num("costLow"),cost_high:num("costHigh"),monetization_eligible:$("monetizationEligible").checked};
    try{const r=await api("/api/opportunities/score",{method:"POST",body:JSON.stringify(body)});msg("opportunityResult","우선순위 점수 "+r.priority_score+" / 100 · 예상치이며 실제 수익이 아닙니다.");}
    catch(err){msg("opportunityResult",err.message,true);}
  });
  $("reviewList").addEventListener("click",async e=>{
    const b=e.target.closest("button[data-action]");if(!b)return;if(!requireToken())return;
    const id=b.dataset.id,action=b.dataset.action;
    try{
      if(action==="stage"){
        const r=await api("/api/production/jobs/"+encodeURIComponent(id)+"/stage-media",{method:"POST"});
        $("stage-"+CSS.escape(id)).textContent="스테이징 완료 · "+r.media_path+" · "+r.size_bytes+" bytes";
        toast("미디어 스테이징 완료. 검수 승인 후 YouTube 업로드를 진행할 수 있습니다.");
      }else{
        const comment=action==="approve"?"Approved after human review":prompt(action==="reject"?"반려 사유":"수정 요청 내용");
        if(comment===null)return;
        const endpoint=action==="approve"?"approve":action==="reject"?"reject":"request-revision";
        await api("/api/review/"+encodeURIComponent(id)+"/"+endpoint,{method:"POST",body:JSON.stringify({reviewer_id:reviewer,comment})});
        toast("검수 결정이 기록되었습니다.");await refreshAll();
      }
    }catch(err){toast(err.message);}
  });

  $("approvedList").addEventListener("click",async e=>{
    const lateButton=e.target.closest("button[data-resolve-late-id]");
    if(lateButton){
      if(!requireToken())return;
      const id=lateButton.dataset.resolveLateId;
      const videoId=prompt("현재 기록된 영상 ID 또는 늦게 도착한 응답의 영상 ID 중 선택하세요.");
      if(videoId===null||!videoId.trim())return;
      const note=prompt("YouTube Studio에서 선택한 영상 ID를 확인한 근거를 입력하세요.");
      if(note===null||!note.trim())return;
      try{
        await api("/api/youtube/uploads/"+encodeURIComponent(id)+"/resolve-late-result",{method:"POST",body:JSON.stringify({operator_id:reviewer||"operator",video_id:videoId.trim(),note:note.trim()})});
        toast("늦은 업로드 결과를 확정했습니다.");await refreshAll();
      }catch(err){$("upload-"+CSS.escape(id)).textContent=err.message;toast(err.message);}
      return;
    }
    const reconcileButton=e.target.closest("button[data-reconcile-id]");
    if(reconcileButton){
      if(!requireToken())return;
      const id=reconcileButton.dataset.reconcileId;
      const outcome=prompt("YouTube Studio에서 해당 작업의 업로드 결과를 확인한 뒤 입력하세요: uploaded 또는 not_uploaded");
      if(outcome===null)return;
      const normalized=outcome.trim().toLowerCase();
      if(!["uploaded","not_uploaded"].includes(normalized)){toast("uploaded 또는 not_uploaded만 입력할 수 있습니다.");return;}
      let videoId=null;
      if(normalized==="uploaded"){
        videoId=prompt("YouTube Studio에서 확인한 영상 ID를 입력하세요.");
        if(videoId===null||!videoId.trim())return;
      }else if(!confirm("YouTube Studio에서 해당 영상이 업로드되지 않았음을 직접 확인하셨습니까? 확인 후에만 재시도를 허용합니다.")){
        return;
      }
      const note=prompt("대조 근거 또는 확인 메모를 입력하세요.");
      if(note===null||!note.trim())return;
      try{
        await api("/api/youtube/uploads/"+encodeURIComponent(id)+"/reconcile",{method:"POST",body:JSON.stringify({outcome:normalized,confirmed:true,video_id:videoId,note:note.trim(),operator_id:reviewer||"operator"})});
        toast("업로드 상태 대조가 기록되었습니다.");await refreshAll();
      }catch(err){$("upload-"+CSS.escape(id)).textContent=err.message;toast(err.message);}
      return;
    }
    const b=e.target.closest("button[data-upload-id]");if(!b)return;if(!requireToken())return;
    const id=b.dataset.uploadId;
    const title=prompt("YouTube 영상 제목 (최대 100자)", "Shorts · "+id.slice(0,8));
    if(title===null)return;
    const cleanTitle=title.trim().slice(0,100);
    if(!cleanTitle){toast("영상 제목을 입력하세요.");return;}
    try{
      const staged=await api("/api/production/jobs/"+encodeURIComponent(id)+"/stage-media",{method:"POST"});
      $("upload-"+CSS.escape(id)).textContent="미디어 스테이징 완료 · "+staged.size_bytes+" bytes";
      await api("/api/youtube/upload/"+encodeURIComponent(id),{method:"POST",body:JSON.stringify({media_path:staged.media_path,title:cleanTitle,description:"Created with NEXUS STUDIO PRO",tags:["shorts"],category_id:"22"})});
      toast("YouTube 비공개 업로드 완료");await refreshAll();
    }catch(err){$("upload-"+CSS.escape(id)).textContent=err.message;toast(err.message);}
  });
  $("scheduleForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{await api("/api/schedules",{method:"POST",body:JSON.stringify({name:$("scheduleName").value,interval_seconds:Number($("scheduleHours").value)*3600,brand:$("scheduleBrand").value,region:$("scheduleRegion").value,language:$("scheduleLanguage").value,topic:$("scheduleTopic").value})});toast("예약 제작 등록 완료");await loadSchedules();}
    catch(err){toast(err.message);}
  });
  $("ledgerForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{await api("/api/finance/ledger",{method:"POST",body:JSON.stringify({brand:$("ledgerBrand").value,region:$("ledgerRegion").value,entry_type:$("ledgerType").value,amount:Number($("ledgerAmount").value),currency:$("ledgerCurrency").value,source_type:"operator_receipt",source_reference:$("ledgerReference").value,occurred_at:new Date($("ledgerDate").value+"T12:00:00Z").toISOString(),note:"Entered via NEXUS dashboard"})});msg("ledgerMessage","거래 장부 기록 완료");await Promise.all([loadMetrics(),loadFinance()]);}
    catch(err){msg("ledgerMessage",err.message,true);}
  });
  $("ledgerCurrency").addEventListener("change",()=>loadFinance().catch(e=>toast(e.message)));
  $("ledgerDate").value=new Date().toISOString().slice(0,10);
  loadBrands().then(()=>{setConnection(false,"API 인증 필요");}).catch(e=>setConnection(false,"API 연결 실패: "+e.message));
})();