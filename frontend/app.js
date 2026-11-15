(() => {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let reviewer = "operator";
  let brands = [];
  let toastTimer;
  let recommendationExposureObserver;
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
      const artifacts=item.artifacts||[];
      const video=artifacts.find(a=>a.artifact_type==="video");
      const scriptArtifact=artifacts.find(a=>a.artifact_type==="text"&&a.stage==="script");
      const audioArtifact=artifacts.find(a=>a.artifact_type==="audio");
      const qualityArtifact=artifacts.find(a=>a.stage==="quality_check"&&a.artifact_type==="report");
      const quality=qualityArtifact?.metadata||{};
      const qualityBlocks=Array.isArray(quality.blockers)?quality.blockers:[];
      const qualityWarnings=Array.isArray(quality.warnings)?quality.warnings:[];
      const scriptText=scriptArtifact?.metadata?.script;
      const scriptPreview=typeof scriptText==="string"&&scriptText.trim()
        ? '<details class="review-script"><summary>생성 대본 검수</summary><pre>'+esc(scriptText)+'</pre></details>'
        : '';
      const policy=scriptArtifact?.metadata?.policy_preflight||{};
      const policyLabels={blocked:"제작 차단",review_required:"확인 필요",ready_for_human_review:"사전 항목 확인 · 사람 승인 필요"};
      const policyItems=Array.isArray(policy.required_confirmations)?policy.required_confirmations:[];
      const policyBlocks=Array.isArray(policy.blocking_reasons)?policy.blocking_reasons:[];
      const policyApprovalBlocks=Array.isArray(policy.approval_blockers)?policy.approval_blockers:[];
      const policySummary=policy.status
        ? '<section class="review-policy"><strong>플랫폼 정책 사전검사 · '+esc(policyLabels[policy.status]||policy.status)+'</strong>'
          +(policyBlocks.length?'<p>차단 사유: '+policyBlocks.map(esc).join(', ')+'</p>':'')
          +(policyApprovalBlocks.length?'<p><strong>승인 차단(해결 전 승인 불가):</strong> '+policyApprovalBlocks.map(esc).join(', ')+'</p>':'')
          +(policyItems.length?'<p>추가 확인: '+policyItems.map(esc).join(', ')+'</p>':'')
          +(policyApprovalBlocks.length?'<button class="button button-outline" data-action="policy-evidence" data-id="'+esc(item.job_id)+'">필수 정책 정보 입력</button>':'')
          +'<small>YouTube / TikTok 사전 위험 점검입니다. 영상 전체 검사나 플랫폼 승인·수익화 보증이 아니며, 게시 전 최신 공식 정책과 사용 권리를 확인해야 합니다.</small></section>'
        : '<section class="review-policy"><strong>정책 사전검사 자료 없음</strong><small>게시 전 권리·AI 표시·사실성·독창성을 직접 확인하세요.</small></section>';
      const qualityLabels={blocked:"품질 게이트 차단",review_required:"사람 확인 필요",ready_for_human_review:"메타데이터 검사 통과 · 사람 승인 필요"};
      const mediaCheck=quality.media_inspection||{};
      const signalCheck=mediaCheck.signal_analysis||{};
      const speechCheck=quality.speech_alignment||{};
      const speechSummary=speechCheck.status
        ? '<p>음성-대본 대조: '+esc(speechCheck.status)+' · '+(speechCheck.match_rate===null||speechCheck.match_rate===undefined?'유사도 산출 불가':esc((Number(speechCheck.match_rate)*100).toFixed(1))+'% 일치 추정')+' · ASR '+esc(speechCheck.provider||"미설정")+'</p>'
        : '';
      const captionCheck=quality.caption_alignment||{};
      const timingCheck=captionCheck.timing_analysis||{};
      const captionSummary=captionCheck.status
        ? '<p>자막-음성/대본 대조: '+esc(captionCheck.status)+' · '+(captionCheck.match_rate===null||captionCheck.match_rate===undefined?'대조 불가':esc((Number(captionCheck.match_rate)*100).toFixed(1))+'% 일치 추정')+' · 추출 '+esc(captionCheck.extraction_status||"미실행")+'</p>'
          +(timingCheck.status==="analyzed"?'<p>자막 타이밍: '+esc(timingCheck.cue_count)+'개 구간 · 겹침 '+esc(timingCheck.overlap_count)+'개 · 빠른 읽기 '+esc(timingCheck.fast_reading_count)+'개 · 긴 공백 '+esc(timingCheck.long_gap_count)+'개</p>':'')
        : '';
      const originalityCheck=quality.originality_check||{};
      const similarScripts=Array.isArray(originalityCheck.similar_matches)?originalityCheck.similar_matches:[];
      const originalitySummary=similarScripts.length
        ? '<p>유사 대본 주의: '+similarScripts.map(match=>esc(match.brand||"브랜드 미상")+' · '+esc(match.topic||"주제 미상")+' · '+esc((Number(match.similarity)*100).toFixed(1))+'%').join(' / ')+'</p>'
        : '';
      const mediaSummary=mediaCheck.status==="inspected"
        ? '<p>실제 파일 검사: '+esc(mediaCheck.width)+'×'+esc(mediaCheck.height)+' px · '+esc(Number(mediaCheck.duration_seconds).toFixed(1))+'초 · 영상 '+esc(mediaCheck.video_codec||"알 수 없음")+' · 오디오 '+esc(mediaCheck.audio_codec||"없음")+' · 자막 스트림 '+(mediaCheck.subtitle_stream_present?"있음":"없음")+'</p>'
          +(signalCheck.status==="analyzed"?'<p>신호 분석: 검은 화면 구간 '+esc((signalCheck.black_segments||[]).length)+'개 · 무음 구간 '+esc((signalCheck.silence_segments||[]).length)+'개</p>':'')
        : '';
      const qualitySummary=qualityArtifact
        ? '<section class="review-policy"><strong>자동 제작 품질 검사 · '+esc(qualityLabels[quality.status]||quality.status)+'</strong>'
          +mediaSummary
          +speechSummary
          +captionSummary
          +originalitySummary
          +(qualityBlocks.length?'<p>차단 사유: '+qualityBlocks.map(esc).join(', ')+'</p>':'')
          +(qualityWarnings.length?'<p>확인 경고: '+qualityWarnings.map(esc).join(', ')+'</p>':'')
          +'<small>'+esc(quality.verification_boundary||"메타데이터 기반 검사이며 실제 미디어 검증은 아닙니다.")+'</small></section>'
        : '<section class="review-policy"><strong>자동 제작 품질 검사 자료 없음</strong><small>영상·음성·자막·대본을 직접 확인하세요.</small></section>';
      const audioPreview=audioArtifact?.artifact_url
        ? '<div class="review-audio"><label>내레이션 미리 듣기</label><audio controls preload="metadata" src="'+esc(audioArtifact.artifact_url)+'"></audio></div>'
        : '';
      const profile=item.brand_profile||{};
      const rules=Array.isArray(profile.review_rules)?profile.review_rules:[];
      const guidance=profile.risk_level
        ? '<section class="review-guidance"><div><strong>브랜드 검수 기준</strong><span class="risk-level risk-'+esc(profile.risk_level)+'">위험도 '+esc(profile.risk_level)+'</span></div>'+(profile.positioning?'<p>'+esc(profile.positioning)+'</p>':'')+(rules.length?'<ul>'+rules.map(rule=>'<li>'+esc(rule)+'</li>').join('')+'</ul>':'')+'</section>'
        : '';
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · '+esc(item.current_stage||item.status)+'</p><div class="review-meta">JOB '+esc(item.job_id)+' · '+esc(item.updated_at||"")+'</div>'+guidance+policySummary+qualitySummary+scriptPreview+audioPreview+(video?'<p><a target="_blank" rel="noopener" href="'+esc(video.artifact_url)+'">렌더링 영상 열기 ↗</a></p>':'')+'<div class="inline-message" id="stage-'+esc(item.job_id)+'"></div></div><div class="review-actions"><button class="button button-quiet" data-action="stage" data-id="'+esc(item.job_id)+'">미디어 스테이징</button><button class="button button-primary" data-action="approve" data-id="'+esc(item.job_id)+'" data-policy-status="'+esc(policy.status||"missing")+'" data-policy-required="'+esc(policyItems.join(", "))+'" data-policy-blockers="'+esc(policyApprovalBlocks.join(", "))+'" data-quality-status="'+esc(quality.status||"missing")+'" data-quality-warnings="'+esc(qualityWarnings.join(", "))+'" '+((policyApprovalBlocks.length||qualityBlocks.length)?'disabled title="필수 정책 또는 품질 차단 항목 해결 전 승인할 수 없습니다"':'')+'>승인</button><button class="button button-outline" data-action="revision" data-id="'+esc(item.job_id)+'">수정 요청</button><button class="button button-quiet" data-action="reject" data-id="'+esc(item.job_id)+'">반려</button></div></article>';
    }).join(""):'<div class="empty-state">현재 검수 대기 콘텐츠가 없습니다.</div>';
  }

  function renderLifecycleTrace(data,performance=null){
    const job=data.job||{},production=data.production||{},review=data.review||{};
    const metrics=performance||data.performance||{};
    const metricRows=(metrics.state_durations||[]).map(item=>'<div><small>'+esc(item.stage)+' · '+esc(item.status)+'</small><b>'+esc(item.observed_seconds)+'초</b></div>').join("");
    const performanceHtml='<section class="review-policy lifecycle-performance"><strong>단계별 체류시간 분석</strong>'+
      '<p>관측 누적 '+esc(metrics.total_observed_seconds??0)+'초 · 측정 기준: 큐 상태 체류시간</p>'+
      (metricRows?'<div class="finance-summary">'+metricRows+'</div>':'<p>분석할 큐 이벤트가 아직 충분하지 않습니다.</p>')+
      (metrics.bottleneck?'<p>가장 긴 체류 상태: '+esc(metrics.bottleneck.stage)+' ('+esc(metrics.bottleneck.observed_seconds)+'초)</p>':'')+
      '<small>공급자 실행시간이나 렌더링 CPU 시간과 동일하지 않습니다. 표본 부족 시 병목 확정에 사용하지 않습니다.</small></section>';
    const publishing=data.publishing||{},youtube=publishing.youtube||{},tiktok=publishing.tiktok||{};
    const latest=review.latest||{};
    const events=(data.timeline||[]).slice(-20).reverse();
    const stageLabels={queue:"작업 큐",production:"제작",human_review:"사람 검수",youtube:"YouTube",tiktok:"TikTok"};
    const eventHtml=events.length
      ? '<ol>'+events.map(event=>'<li><strong>'+esc(stageLabels[event.stage]||event.stage)+' · '+esc(event.event||"event")+'</strong> · '+esc(event.outcome||"기록")+(event.attempt_id?' · 시도 '+esc(event.attempt_id):"")+(event.reference_id?' · 참조 '+esc(event.reference_id):"")+' <small>'+esc(event.occurred_at||"")+'</small></li>').join("")+'</ol>'
      : '<p>아직 통합 이벤트가 없습니다.</p>';
    return performanceHtml+'<section class="review-policy lifecycle-trace"><strong>통합 작업 이력</strong>'+
      '<p>큐 · '+esc(job.status||"unknown")+' / 제작 · '+esc(production.status||"unknown")+
      ' ('+esc(production.current_stage||"단계 미기록")+')</p>'+
      '<p>최근 검수 · '+esc(latest.decision||"검수 기록 없음")+
      (latest.reviewer_id?' · '+esc(latest.reviewer_id):"")+
      (latest.created_at?' · '+esc(latest.created_at):"")+'</p>'+
      '<p>YouTube · '+esc(youtube.status||"not_started")+
      (youtube.video_id?' · '+esc(youtube.video_id):"")+
      ' / TikTok · '+esc(tiktok.status||"not_started")+
      (tiktok.video_id?' · '+esc(tiktok.video_id):"")+
      (tiktok.publish_id?' · publish '+esc(tiktok.publish_id):"")+'</p>'+
      '<strong>최근 통합 이벤트 (최대 20개)</strong>'+eventHtml+'</section>';
  }

  function renderLifecycleOperations(consistency,recovery){
    const severityLabels={blocker:"조치 전 게시·재처리 차단",warning:"확인 필요"};
    const findings=(consistency.findings||[]);
    const findingHtml=findings.length
      ? '<ul>'+findings.map(item=>'<li><strong>'+esc(severityLabels[item.severity]||item.severity)+' · '+esc(item.code)+'</strong><p>'+esc(item.message)+'</p><small>단계: '+esc(item.stage||"")+'</small></li>').join("")+'</ul>'
      : '<p>현재 기록에서 자동 탐지된 상태 불일치가 없습니다.</p>';
    const steps=(recovery.steps||[]);
    const stepHtml=steps.length
      ? '<ol>'+steps.map(item=>'<li><strong>'+esc(item.platform)+' · '+esc(item.instruction)+'</strong><p>우선순위: '+esc(item.priority)+'</p>'+(item.endpoint?'<code>'+esc(item.method||"GET")+' '+esc(item.endpoint)+'</code>':'')+
        ((item.requires_operator_evidence||[]).length?'<p>필요 증거: '+item.requires_operator_evidence.map(esc).join(" · ")+'</p>':'')+'</li>').join("")+'</ol>'
      : '<p>현재 상태에서 추가 복구 조치가 자동 제안되지 않았습니다.</p>';
    return '<section class="review-policy lifecycle-operations"><strong>상태 일관성 진단 · '+esc(consistency.status||"unknown")+'</strong>'+
      '<p>'+ (consistency.read_only?"읽기 전용 진단 · 원격 게시·재시도 없음":"")+'</p>'+findingHtml+
      '<strong>운영자 복구 절차</strong>'+stepHtml+
      '<p><strong>재처리 정책:</strong> '+esc(recovery.retry_policy||"별도 확인 필요")+'</p>'+
      '<small>이 화면은 절차 안내입니다. 복구·재게시·재시도는 별도 승인과 원격 상태 확인 없이는 실행되지 않습니다.</small></section>';
  }

  async function loadApproved(){
    const data=await api("/api/review/approved?limit=100");
    const items=data.items||[];
    $("approvedList").innerHTML=items.length?items.map(item=>{
      const video=(item.artifacts||[]).find(a=>a.artifact_type==="video");
      const uncertain=!!item.upload_reconciliation_required;
      const status=item.upload_status||"not_uploaded";
      const lateIds=(item.upload_events||[]).filter(event=>event.event_type==="late_remote_success"&&event.video_id).map(event=>event.video_id);
      const lateIdSummary=lateIds.length?'<p>늦게 확인된 YouTube 영상 ID: '+lateIds.map(esc).join(" · ")+'</p>':"";
      const existingIdSummary=item.upload_video_id?'<p>YouTube 영상 ID: '+esc(item.upload_video_id)+'</p>':"";
      const action=status==="late_success_review_required"
        ? '<button class="button button-outline" data-resolve-late-id="'+esc(item.job_id)+'">YouTube 늦은 결과 확정</button>'
        : (uncertain
          ? '<button class="button button-outline" data-reconcile-id="'+esc(item.job_id)+'">YouTube 결과 대조</button>'
          : (status==="uploading"
            ? '<button class="button button-quiet" disabled>YouTube 업로드 진행 중</button>'
            : (status==="uploaded"
              ? '<button class="button button-quiet" disabled>YouTube 업로드 완료</button>'
              : '<button class="button button-primary" data-upload-id="'+esc(item.job_id)+'">YouTube 비공개 업로드</button>')));
      const statusText=status==="late_success_review_required"?"늦은 업로드 성공 · 운영자 확인 필요":(uncertain?"업로드 결과 확인 필요":(status==="uploading"?"업로드 진행 중":(status==="failed"?"이전 업로드 실패 · 재시도 가능":(status==="uploaded"?"업로드 완료":"업로드 대기"))));
      const tiktokStatus=item.tiktok_status||"not_selected";
      const tiktokLabels={not_started:"업로드 대기",initializing:"게시 초기화",uploading:"미디어 전송 완료 · 게시 처리 대기",processing:"TikTok 처리 중",send_to_inbox:"TikTok 앱에서 게시 마무리 필요",publish_complete:"게시 완료",failed:"게시 실패",reconciliation_required:"원격 결과 확인 필요"};
      const tiktokSummary=item.tiktok_eligible
        ? '<p>TikTok · '+esc(tiktokLabels[tiktokStatus]||tiktokStatus)+(item.tiktok_video_id?' · 영상 ID '+esc(item.tiktok_video_id):'')+'</p>'
        : (tiktokStatus==="not_selected"?'':'<p>TikTok · 현재 정책 정보 또는 플랫폼 선택 확인 필요</p>');
      let tiktokAction="";
      if(item.tiktok_eligible){
        if(tiktokStatus==="publish_complete"){
          tiktokAction='<button class="button button-quiet" disabled>TikTok 게시 완료</button>';
        }else if(tiktokStatus==="reconciliation_required"){
          tiktokAction=item.tiktok_publish_id
            ? '<button class="button button-outline" data-tiktok-refresh-id="'+esc(item.job_id)+'">TikTok 결과 대조</button>'
            : '<button class="button button-quiet" disabled>TikTok 운영자 확인 필요</button>';
        }else if(["initializing","uploading","processing","send_to_inbox"].includes(tiktokStatus)){
          tiktokAction='<button class="button button-outline" data-tiktok-refresh-id="'+esc(item.job_id)+'">TikTok 상태 갱신</button>';
        }else{
          tiktokAction='<button class="button button-secondary" data-tiktok-publish-id="'+esc(item.job_id)+'">TikTok 비공개 게시</button>';
        }
      }
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · 승인 완료 · YouTube '+esc(statusText)+'</p><div class="review-meta">JOB '+esc(item.job_id)+'</div>'+(video?'<p><a target="_blank" rel="noopener" href="'+esc(video.artifact_url)+'">원본 영상 열기 ↗</a></p>':'')+existingIdSummary+lateIdSummary+tiktokSummary+'<div class="inline-message" id="upload-'+esc(item.job_id)+'"></div><div id="lifecycle-'+esc(item.job_id)+'"></div></div><div class="review-actions">'+action+tiktokAction+'<button class="button button-quiet" data-lifecycle-id="'+esc(item.job_id)+'">상태·복구 진단</button></div></article>';
    }).join(""):'<div class="empty-state">승인 완료 후 게시 대기 중인 콘텐츠가 없습니다.</div>';
  }
  async function loadTrends(){
    const data=await api("/api/trends?limit=12");
    const active=brands.filter(b=>b.active);
    $("trendList").innerHTML=(data.items||[]).map(x=>{
      const region=x.region||"";
      const language=region==="KR"?"ko":(region==="JP"?"ja":"en");
      const eligible=active.filter(b=>b.config?.regions?.includes(region)&&b.config?.languages?.includes(language));
      const options=eligible.map(b=>'<option value="'+esc(b.slug)+'">'+esc(b.name)+'</option>').join("");
      const controls=x.id&&eligible.length
        ? '<div class="trend-actions"><select aria-label="제작 브랜드" data-trend-brand="'+esc(x.id)+'">'+options+'</select><button class="button button-secondary" data-trend-draft="'+esc(x.id)+'" data-trend-language="'+language+'">이 트렌드로 제작 기획</button></div>'
        : '<small class="trend-unavailable">해당 지역을 지원하는 활성 브랜드가 없어 바로 제작할 수 없습니다.</small>';
      return '<div class="data-item trend-item"><b>'+esc(x.title||x.query||"Untitled signal")+'</b><small>'+esc(region)+' · '+esc(x.source||"")+' · '+esc(x.published_at||x.collected_at||"")+'</small>'+controls+'</div>';
    }).join("")||'<div class="empty-state">저장된 트렌드 신호가 없습니다.</div>';
  }

  async function loadRenderedExposureReport(runId){
    if(!runId)return;
    const report=await api("/api/recommendations/exposures/"+encodeURIComponent(runId)+"/report");
    $("recommendationExposureSummary").textContent=
      "화면 표시 트렌드 "+Number(report.visible_trend_card_count||0)+"개 · 미표시 "+
      Number(report.unseen_trend_card_count||0)+"개 · 표시 확인 "+
      Number(report.render_impression_count||0)+"회 · 노출 후 제작 선택 "+
      Number(report.selected_after_exposure_count||0)+"건 · 실측 성과 "+
      Number(report.measured_outcome_count||0)+"건 · 인과 효과 미측정";
  }

  function observeRenderedRecommendationCards(runId){
    if(recommendationExposureObserver)recommendationExposureObserver.disconnect();
    const cards=Array.from(document.querySelectorAll("[data-recommendation-exposure]"));
    if(!runId||!cards.length||!("IntersectionObserver" in window)){
      $("recommendationExposureSummary").textContent=
        "현재 브라우저에서 화면 표시 측정을 지원하지 않거나 표시할 추천 카드가 없습니다.";
      return;
    }
    recommendationExposureObserver=new IntersectionObserver(entries=>{
      for(const entry of entries){
        const card=entry.target;
        if(entry.isIntersecting&&entry.intersectionRatio>=0.5){
          if(card.dataset.exposureRecorded==="true"||card.dataset.exposureTimer)continue;
          const started=Date.now();
          card.dataset.exposureTimer=setTimeout(async()=>{
            delete card.dataset.exposureTimer;
            if(document.visibilityState!=="visible"||card.dataset.exposureRecorded==="true")return;
            const visibilityMs=Math.min(30000,Math.max(1000,Date.now()-started));
            try{
              const result=await api("/api/recommendations/exposures/rendered",{
                method:"POST",body:JSON.stringify({run_id:runId,exposures:[{
                  event_id:crypto.randomUUID(),trend_id:card.dataset.trendId,
                  visibility_ms:visibilityMs
                }]})
              });
              card.dataset.exposureRecorded="true";
              $("recommendationExposureSummary").textContent=
                "실제 화면 표시 확인 "+Number(result.recorded_count||0)+
                "건 기록 · 개인정보 식별자 미저장 · 무작위 실험 아님";
              await loadRenderedExposureReport(runId);
            }catch(error){
              $("recommendationExposureSummary").textContent=
                "노출 기록 실패: "+error.message+" · 추천 갱신 후 재시도할 수 있습니다.";
            }
          },1000);
        }else if(card.dataset.exposureTimer){
          clearTimeout(card.dataset.exposureTimer);
          delete card.dataset.exposureTimer;
        }
      }
    },{threshold:[0,0.5,1]});
    cards.forEach(card=>recommendationExposureObserver.observe(card));
    $("recommendationExposureSummary").textContent=
      "추천 카드 화면 표시 확인 대기 중 · 50% 이상 1초 조건 · 사용자 식별정보 미수집";
  }

  async function loadTrendRecommendations(){
    const region=$("trendRegion").value;
    const data=await api("/api/trends/recommendations/snapshot?region="+encodeURIComponent(region)+"&limit=20",{method:"POST"});
    const items=data.items||[];
    $("trendRecommendations").innerHTML=items.map(item=>{
      const trend=item.trend||{};
      const candidates=item.brand_candidates||[];
      const language=region==="KR"?"ko":(region==="JP"?"ja":"en");
      const languageFamily=language.toLowerCase().split("-")[0];
      const options=candidates.filter(x=>(x.supported_languages||[]).some(value=>
        String(value).toLowerCase().split("-")[0]===languageFamily
      )).map(x=>{
          const decision=x.human_decision?.decision;
          const suffix=decision==="skipped"?" · 이전 제외":(decision==="selected"?" · 기획 등록":"");
          return '<option value="'+esc(x.brand)+'" data-candidate-id="'+esc(x.evaluation_candidate_id||"")+'">'+esc(x.brand_name+suffix)+'</option>';
        }).join("");
      const controls=trend.id&&options
        ? '<div class="trend-actions"><select aria-label="추천 제작 브랜드" data-recommend-brand="'+esc(trend.id)+'">'+options+'</select><button type="button" class="button button-secondary" data-recommend-draft="'+esc(trend.id)+'" data-recommend-language="'+language+'">추천 브랜드로 기획</button><button type="button" class="button button-quiet" data-recommend-skip="'+esc(trend.id)+'">이번 후보 제외</button></div>'
        : '<small class="trend-unavailable">현재 시장·언어에 맞는 활성 브랜드가 없습니다.</small>';
      const competitor=item.competitor_context||{};
      const competitorSummary=Number(competitor.observed_videos||0)>0
        ? '<small>경쟁 표본 '+Number(competitor.observed_videos).toLocaleString()+'개 · 주제 일치 '+Number(competitor.topic_matched_videos||0).toLocaleString()+'개 · 일치 영상 중앙 조회수 '+(competitor.median_matched_views===null?'—':Number(competitor.median_matched_views).toLocaleString())+'</small>'
        : '<small>경쟁 영상 표본 미수집</small>';
      const history=item.best_brand?.historical_performance||{};
      const historySummary=history.evidence_status==="observed"
        ? '<small>브랜드 과거 실측 표본 '+Number(history.rate_sample_count)+'개 · 시간당 조회 증가 중앙값 '+Number(history.median_views_per_hour).toLocaleString()+'</small>'
        : '<small>브랜드 과거 성과 표본 '+Number(history.rate_sample_count||0)+'개 · 비교 근거 제한</small>';
      const topicHistory=item.best_brand?.topic_performance||{};
      const topicHistorySummary=topicHistory.evidence_status==="observed"
        ? '<small>동일 주제·시장 실측 '+Number(topicHistory.matched_video_count)+'개 · 시간당 조회 증가 중앙값 '+Number(topicHistory.median_views_per_hour).toLocaleString()+' · 1,000회당 상호작용 '+(topicHistory.median_interactions_per_1000_view_delta===null?'—':Number(topicHistory.median_interactions_per_1000_view_delta).toFixed(1))+'</small>'
        : '<small>동일 주제·시장 실측 '+Number(topicHistory.matched_video_count||0)+'개 · 추천 점수 미반영(최소 3개 표본 필요)</small>';
      const cohortContext=item.best_brand?.comparable_cohort_performance||{};
      const cohortRows=(cohortContext.cohorts||[]).slice(0,2);
      const cohortSummary=cohortRows.length
        ? '<small>비교 코호트 · '+cohortRows.map(x=>esc(x.publication_age_bucket)+' / '+esc(x.duration_bucket)+' · '+Number(x.sample_count)+'개 · '+Number(x.median_views_per_hour||0).toLocaleString()+' views/hour').join(' | ')+'</small>'
        : '<small>동일 브랜드·시장·주제의 비교 코호트 표본 부족</small>';
      return '<div class="data-item trend-item" data-recommendation-exposure data-trend-id="'+esc(trend.id||"")+'" data-run-id="'+esc(data.evaluation_run_id||"")+'"><div class="recommendation-head"><b>'+esc(trend.title||"Untitled trend")+'</b><strong>'+Number(item.recommendation_score||0).toFixed(1)+'/100</strong></div><small>'+esc(trend.region||"")+' · 최신성 '+Number(item.freshness_score||0).toFixed(1)+' · '+esc(item.score_type||"")+'</small>'+(item.best_brand?'<small>최적 브랜드: '+esc(item.best_brand.brand_name)+' · 적합도 '+Number(item.best_brand.fit_score||0).toFixed(1)+'</small>':'<small>적합 브랜드 미확인</small>')+topicHistorySummary+cohortSummary+historySummary+competitorSummary+controls+'<small class="recommendation-caveat">과거 실측값은 동일 브랜드·시장·주제 및 게시 경과·영상 길이별 비교 표본을 별도로 표시하며, 현재 추천 점수에는 반영되지 않습니다. 경쟁 지표도 저장된 최대 10개 채널의 최근 영상 표본으로 시장 전체 수요나 수익을 뜻하지 않습니다.</small></div>';
    }).join("")||'<div class="empty-state">선택한 시장에 추천할 트렌드가 없습니다.</div>';
    observeRenderedRecommendationCards(data.evaluation_run_id);
  }

  async function loadSchedules(){
    const [data,outbox]=await Promise.all([api("/api/schedules"),api("/api/schedules/outbox")]);
    const schedules=(data.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.name)+' · '+(x.active?"활성":"중지")+'</b><small>'+esc(x.payload.brand)+' · '+esc(x.payload.region)+' · 다음 실행 '+esc(x.next_run_at)+'</small></div>').join("")||'<div class="empty-state">등록된 예약이 없습니다.</div>';
    const dispatches=(outbox.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.status)+' · '+esc(x.schedule_id)+'</b><small>'+esc(x.scheduled_for)+' · attempts '+x.attempts+(x.last_error?' · '+esc(x.last_error):'')+'</small></div>').join("");
    $("scheduleList").innerHTML='<div class="notice">Outbox pending/retry: '+Number(outbox.pending_retries||0)+' · dispatched: '+Number((outbox.counts||{}).dispatched||0)+'</div>'+schedules+'<h4>예약 실행 복구 로그</h4>'+(dispatches||'<div class="empty-state">예약 실행 이력이 없습니다.</div>');
  }
  async function loadOpportunities(){
    const data=await api("/api/opportunities?limit=20");
    const items=data.opportunities||[];
    $("opportunityList").innerHTML=items.length?items.map((item,index)=>{
      const scenario=item.scenario||{};
      const context=scenario.competitive_context||{};
      const penalty=scenario.score_breakdown?.competitor_pressure_penalty||0;
      return '<div class="data-item opportunity-rank-item"><div class="opportunity-rank-head"><b>#'+(index+1)+' '+esc(item.title||"Untitled opportunity")+'</b><strong>'+Number(item.priority_score||0).toFixed(1)+'/100</strong></div><small>'+esc(item.currency||"")+' · 예상 순이익 '+esc(scenario.net_profit?.low??"—")+' ~ '+esc(scenario.net_profit?.high??"—")+' · 경쟁 조정 -'+Number(penalty).toFixed(1)+'점</small><small>경쟁 표본 '+Number(context.observed_videos||0)+'개 · 주제 일치 '+Number(context.topic_matched_videos||0)+'개 · '+esc(item.created_at||"")+'</small></div>';
    }).join(""):'<div class="empty-state">저장된 수익성 평가가 없습니다.</div>';
  }

  async function loadInsights(){
    const [data,evaluation,collection,snapshots,tiktokMetrics,youtubeAnalytics]=await Promise.all([
      api("/api/performance/insights"),
      api("/api/recommendations/evaluation"),
      api("/api/metrics/collection-status"),
      api("/api/recommendations/evaluation/snapshots?limit=10"),
      api("/api/tiktok/metrics?limit=100"),
      api("/api/youtube/analytics-metrics?limit=100")
    ]);
    const brands=(data.brands||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+Number(x.view_delta||0).toLocaleString()+' views (snapshot delta)</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+' · 미측정 '+x.unmeasured_videos+' · '+esc((x.recommendations||[]).map(r=>r.action).join(" / "))+'</small></div>').join("");
    const regions=(data.regions||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+Number(x.view_delta||0).toLocaleString()+' views</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+'</small></div>').join("");
    const videos=(data.videos||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic)+'</b><small>'+esc(x.measurement_status)+' · snapshots '+x.snapshot_count+(x.view_delta===undefined?"":" · Δ "+Number(x.view_delta).toLocaleString())+'</small></div>').join("");
    const cohorts=(data.cohorts||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic_signature)+' · '+esc(x.duration_bucket)+' · '+esc(x.publication_age_bucket)+'</b><small>'+esc(x.format)+' · 비교 표본 '+Number(x.sample_count||0)+'개 · 중앙값 '+Number(x.median_views_per_hour||0).toLocaleString()+' views/hour · 평균 시청률 '+(x.median_average_view_percentage===null||x.median_average_view_percentage===undefined?'—':Number(x.median_average_view_percentage).toFixed(1)+'%')+' · '+esc(x.evidence_status)+' · 추천 점수 반영 안 함</small></div>').join("");
    const cohortInsights=(data.cohort_insights||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic_signature)+' · '+esc(x.status)+'</b><small>표본 '+Number(x.sample_count||0)+'개 · 비교 코호트 '+Number(x.comparison_cohort_count||0)+'개 · '+esc(x.suggested_action)+' · 점수 조정 '+Number(x.ranking_score_adjustment||0)+'</small></div>').join("");
    const youtubeAnalyticsVideos=(youtubeAnalytics.items||[]).map(x=>'<div class="data-item"><b>YouTube Analytics · '+esc(x.video_id)+' · '+Number(x.views||0).toLocaleString()+' views</b><small>Shorts engaged views '+Number(x.engaged_views||0).toLocaleString()+' · 평균 시청 '+Number(x.average_view_duration||0).toFixed(1)+'초 · 평균 시청률 '+(x.average_view_percentage===null?"—":Number(x.average_view_percentage).toFixed(1)+'%')+'</small><small>시청 시간 '+Number(x.estimated_minutes_watched||0).toFixed(1)+'분 · 좋아요 '+Number(x.likes||0).toLocaleString()+' · 댓글 '+Number(x.comments||0).toLocaleString()+' · 공유 '+Number(x.shares||0).toLocaleString()+' · 구독자 증가 '+Number(x.subscribers_gained||0).toLocaleString()+'</small><small>기간 '+esc(x.start_date||"")+' ~ '+esc(x.end_date||"")+' · 수집 '+esc(x.collected_at||"")+'</small></div>').join("");
    const tiktokVideos=(tiktokMetrics.items||[]).map(x=>'<div class="data-item"><b>TikTok · '+esc(x.video_id)+' · '+Number(x.view_count||0).toLocaleString()+' views</b><small>좋아요 '+Number(x.like_count||0).toLocaleString()+' · 댓글 '+Number(x.comment_count||0).toLocaleString()+' · 공유 '+Number(x.share_count||0).toLocaleString()+'</small><small>게시 작업 '+esc(x.job_id)+' · '+esc(x.privacy_level||"SELF_ONLY")+' · 수집 '+esc(x.collected_at||"")+'</small></div>').join("");
    const finance=(data.financial||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+esc(x.currency)+' · net '+money(x.net,x.currency)+'</b><small>매출 '+money(x.revenue,x.currency)+' · 비용 '+money(x.costs,x.currency)+' · '+x.entries+'건</small></div>').join("");
    const collectionPanel='<h4>성과 데이터 수집 상태</h4>'+Object.values(collection.platforms||{}).map(x=>{
      const coverage=x.coverage||{};
      const status=x.status==="succeeded"?"최근 수집 성공":x.status==="running"?"수집 중":x.status==="failed"?"최근 수집 실패":x.status==="not_implemented"?"수집 기능 미구현":x.status==="scope_missing"?"필수 OAuth 권한 필요":x.status==="authorization_failed"?"YouTube OAuth 재연결 필요":x.status==="scope_unverified"?"OAuth 권한 검증 필요":x.status==="waiting_for_uploaded_videos"?"게시 영상 대기":"수집 이력 없음";
      const time=x.last_success_at||"성공 이력 없음";
      return '<div class="data-item"><b>'+esc(x.platform)+' · '+esc(status)+'</b><small>최근 성공 '+esc(time)+' · 최근 오류 '+esc(x.last_error||"없음")+'</small><small>수집 표본 '+Number(coverage.with_snapshot||0)+'/'+Number(coverage.uploaded_videos||coverage.published_videos||0)+' · 미수집 '+Number(coverage.without_snapshot||0)+' · 오래된 스냅샷 '+Number(coverage.stale_snapshots||0)+'</small><small>제공 지표 '+esc((x.available_metrics||[]).join(", ")||"없음")+' · 미제공 지표 '+esc((x.unavailable_metrics||[]).join(", ")||"없음")+'</small></div>';
    }).join("")+'<div class="notice">수집 상태는 저장된 실행 기록 기준입니다. TikTok은 본인 게시 영상에 한해 video.list 권한으로 조회수·좋아요·댓글·공유 수를 수집합니다. 시청 지속시간·리텐션·예상 수익은 제공하지 않습니다. OAuth 재승인 및 앱 권한 승인이 필요할 수 있습니다.</div>';
    const evalStatus=evaluation.status==="holdout_available"?"노출 단위 시계열 홀드아웃 진단 가능":evaluation.status==="holdout_inconclusive"?"홀드아웃 결과 불충분":evaluation.status==="insufficient_run_coverage"?"서로 다른 추천 노출 횟수 부족":"검증 표본 수집 중";
    const within=evaluation.within_run_validation||{};
    const withinStatus=within.status==="holdout_available"?"동일 추천 세트 기준 홀드아웃 가능":"동일 추천 세트 표본 부족";
    const withinRho=within.holdout_median_score_views_spearman;
    const evaluationPanel='<h4>추천 알고리즘 홀드아웃 검증</h4><div class="data-item"><b>'+esc(evalStatus)+' · '+Number(evaluation.measured_outcome_count||0)+'개 실측 / 선택 제작 '+Number(evaluation.selected_production_count||0)+'개</b><small>교차 노출 단순 참고 ρ '+(evaluation.holdout_score_views_spearman===null||evaluation.holdout_score_views_spearman===undefined?"—":Number(evaluation.holdout_score_views_spearman).toFixed(3))+' · 학습 '+Number(evaluation.pre_holdout_count||0)+'개 / 홀드아웃 '+Number(evaluation.holdout_count||0)+'개 · 노출 단위 학습 '+Number(evaluation.pre_holdout_run_count||0)+'개 / 검증 '+Number(evaluation.holdout_run_count||0)+'개</small><small>학습 ρ '+(evaluation.pre_holdout_score_views_spearman===null||evaluation.pre_holdout_score_views_spearman===undefined?"—":Number(evaluation.pre_holdout_score_views_spearman).toFixed(3))+' · 검증 ρ '+(evaluation.holdout_score_views_spearman===null||evaluation.holdout_score_views_spearman===undefined?"—":Number(evaluation.holdout_score_views_spearman).toFixed(3))+' · 연관 안정성 '+esc(evaluation.score_association_stability||"판정 불가")+'</small><small><b>'+esc(withinStatus)+'</b> · 유효 노출 '+Number(within.eligible_run_count||0)+'개 · 학습 '+Number(within.pre_holdout_run_count||0)+'개 / 홀드아웃 '+Number(within.holdout_run_count||0)+'개 · 동일 노출 중앙 Spearman ρ '+(withinRho===null||withinRho===undefined?"—":Number(withinRho).toFixed(3))+' · 순위 ρ '+(within.holdout_median_rank_views_spearman===null||within.holdout_median_rank_views_spearman===undefined?"—":Number(within.holdout_median_rank_views_spearman).toFixed(3))+' · 양의 연관 비율 '+(within.holdout_positive_score_association_share===null||within.holdout_positive_score_association_share===undefined?"—":Math.round(Number(within.holdout_positive_score_association_share)*100)+'%')+'</small><small>'+esc(within.reason||evaluation.reason||"")+'</small><small>'+esc(evaluation.pooled_metric_boundary||"")+'</small><small class="recommendation-caveat">'+esc(evaluation.warning||"")+' 점수 자동 조정은 비활성 상태입니다.</small></div>';
    const snapshotPanel='<h4>불변 검증 이력 · '+Number(snapshots.count||0)+'건</h4>'+(snapshots.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.status)+' · '+esc(x.created_at)+'</b><small>실측 '+Number(x.measured_count||0)+'/'+Number(x.selected_count||0)+' · 홀드아웃 노출 '+Number(x.holdout_run_count||0)+'개 · ρ '+(x.holdout_score_spearman===null||x.holdout_score_spearman===undefined?"—":Number(x.holdout_score_spearman).toFixed(3))+'</small><small>입력 지문 '+esc(String(x.input_fingerprint||"").slice(0,16))+'… · '+esc(x.evaluation_version)+'</small></div>').join("")||'<div class="empty-state">아직 저장된 검증 이력이 없습니다.</div>';
    $("insightList").innerHTML=collectionPanel+evaluationPanel+snapshotPanel+'<h4>브랜드 성과</h4>'+(brands||'<div class="empty-state">업로드된 영상 데이터가 없습니다.</div>')+'<h4>지역별 성과</h4>'+(regions||'<div class="empty-state">지역별 데이터가 없습니다.</div>')+'<h4>비교 가능한 성과 코호트</h4>'+(cohorts||'<div class="empty-state">비교 조건을 만족하는 측정 표본이 아직 없습니다.</div>')+'<h4>성과 기반 다음 제작 실험 제안 (점수 자동 변경 없음)</h4>'+(cohortInsights||'<div class="empty-state">비교 가능한 표본이 부족합니다. 동일 조건의 측정 영상이 더 필요합니다.</div>')+'<h4>YouTube 영상별 측정 상태</h4>'+(videos||'<div class="empty-state">YouTube 영상 측정 데이터가 없습니다.</div>')+'<h4>YouTube 고급 분석 · 시청 지속시간/평균 시청률</h4>'+(youtubeAnalyticsVideos||'<div class="empty-state">YouTube Analytics 데이터가 없습니다. yt-analytics.readonly 권한이 포함된 OAuth 재승인 후 수집됩니다.</div>')+'<h4>TikTok 영상 성과 · 조회수/좋아요/댓글/공유</h4>'+(tiktokVideos||'<div class="empty-state">TikTok 성과 스냅샷이 없습니다. video.list 권한 승인 후 수집됩니다.</div>')+'<h4>실제 기록 금융 데이터 (통화별)</h4>'+(finance||'<div class="empty-state">기록된 금융 데이터가 없습니다.</div>')+'<div class="notice">'+(data.limitations||[]).map(esc).join(" · ")+'</div>';
  }

  async function loadRecommendationExperiments(){
    const data=await api("/api/recommendations/experiments?limit=20");
    const items=data.items||[];
    $("recommendationExperimentList").innerHTML=items.length?items.map(item=>
      '<div class="data-item"><div class="recommendation-head"><b>'+esc(item.name)+'</b><strong>'+esc(item.status)+'</strong></div>'+
      '<small>대조군 '+Number(item.control_count||0)+' · 처리군 '+Number(item.treatment_count||0)+' · Shadow 배정 '+Number(item.shadow_assignment_count||0)+'</small>'+
      '<small>처리군 비율 '+(Number(item.allocation_basis_points||0)/100).toFixed(0)+'% · 실제 노출 0 · 인과 효과 미측정</small>'+
      '<div class="field-row"><button type="button" class="button button-quiet button-small" data-experiment-shadow="'+esc(item.id)+'">샘플 Shadow 배정</button><button type="button" class="button button-secondary button-small" data-experiment-report="'+esc(item.id)+'">실험 보고서</button></div></div>'
    ).join(""):'<div class="empty-state">등록된 실험 초안이 없습니다.</div>';
  }

  async function loadRecommendationExperimentIntegrity(){
    const target=$("recommendationExperimentIntegrity");
    target.innerHTML='<div class="empty-state">증거 무결성 검사 중…</div>';
    const report=await api("/api/recommendations/experiments/integrity");
    const items=report.items||[];
    const status=report.status==="integrity_warning"?"무결성 경고":"Shadow 전용 · 실제 실험 증거 없음";
    target.innerHTML=
      '<div class="data-item"><b>실험 증거 무결성 · '+esc(status)+'</b>'+
      '<small>실험 '+Number(report.experiment_count||0)+'개 · Shadow 배정 '+Number(report.shadow_assignment_count||0)+'건 · 화면 표시 확인 '+Number(report.rendered_viewport_acknowledgement_count||0)+'건</small>'+
      '<small>검증된 무작위 실제 노출 '+Number(report.verified_randomized_served_exposure_count||0)+'건 · 실험군 연결 '+(report.assignment_exposure_join_available?"가능":"불가")+' · 성과 귀속 '+(report.outcome_attribution_to_experiment_arm_available?"가능":"불가")+'</small>'+
      '<small>외래 키 문제 '+Number(report.foreign_key_issue_count||0)+' · 중복 지문 그룹 '+Number(report.duplicate_fingerprint_group_count||0)+' · 경고 실험 '+Number(report.integrity_warning_experiment_count||0)+'</small>'+
      '<small>실제 배정 '+(report.live_assignment_enabled?"활성":"비활성")+' · 추천 점수 조정 '+Number(report.ranking_score_adjustment||0)+' · 배포 권한 '+(report.deployment_authorized?"허용":"없음")+'</small>'+
      (items.map(item=>'<small>'+esc(item.name)+' · '+esc(item.integrity_status)+' · 배정 '+Number(item.assignment_count||0)+' · 중복검사 '+(item.participant_deduplication_ok?"정상":"경고")+'</small>').join(""))+
      '<div class="notice">'+(report.limitations||[]).map(esc).join(" · ")+'</div></div>';
  }

  async function loadRecommendationExperimentReport(experimentId){
    const report=await api("/api/recommendations/experiments/"+encodeURIComponent(experimentId)+"/report");
    const counts=report.assignment_counts||{};
    $("recommendationExperimentReport").innerHTML=
      '<div class="data-item"><b>'+esc(report.name)+' · '+esc(report.status)+'</b>'+
      '<small>Shadow 배정 — 대조군 '+Number(counts.control||0)+' · 처리군 '+Number(counts.treatment||0)+' · 합계 '+Number(report.shadow_assignment_count||0)+'</small>'+
      '<small>실제 노출 '+Number(report.measured_exposure_count||0)+' · 성과 결과 '+Number(report.outcome_count||0)+' · 인과 효과 '+esc(report.causal_effect_status||"not_measured")+'</small>'+
      '<small>효과 추정치 '+(report.effect_estimate===null||report.effect_estimate===undefined?"—":Number(report.effect_estimate).toFixed(4))+' · 신뢰구간 미산출 · 추천 점수 조정 '+Number(report.ranking_score_adjustment||0)+'</small>'+
      '<div class="notice">'+(report.limitations||[]).map(esc).join(" · ")+'</div></div>';
  }

  function createShadowParticipantKey(){
    if(!window.crypto||!window.crypto.getRandomValues)throw new Error("보안 난수 생성이 지원되는 HTTPS 또는 localhost 환경이 필요합니다.");
    const bytes=new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes,value=>value.toString(16).padStart(2,"0")).join("");
  }

  async function loadPublishingDashboard(){
    const target=$("publishingDashboardList");
    target.innerHTML='<div class="empty-state">YouTube·TikTok 게시 이력을 조회하고 있습니다…</div>';
    const data=await api("/api/publishing/dashboard?limit=100");
    const platforms=data.platforms||{};
    const youtube=platforms.youtube||{},tiktok=platforms.tiktok||{};
    const attention=(data.summary||{}).attention_required||0;
    $("publishingDashboardSummary").innerHTML=
      '<div><small>YouTube 게시 기록</small><b>'+Number(youtube.count||0)+'</b><small>'+Object.entries(youtube.status_counts||{}).map(([k,v])=>esc(k)+' '+Number(v)).join(' · ')+'</small></div>'+
      '<div><small>TikTok 게시 기록 · SELF_ONLY</small><b>'+Number(tiktok.count||0)+'</b><small>'+Object.entries(tiktok.status_counts||{}).map(([k,v])=>esc(k)+' '+Number(v)).join(' · ')+'</small></div>'+
      '<div><small>운영자 확인 필요</small><b class="'+(attention?"missing-text":"ready-text")+'">'+Number(attention)+'</b><small>재조정 '+Number(data.summary?.reconciliation_required||0)+' · 오류 '+Number(data.summary?.errors_present||0)+'</small></div>';
    const statusLabels={uploaded:"업로드 완료",failed:"실패",uploading:"업로드 중",reconciliation_required:"결과 확인 필요",late_success_review_required:"지연 성공 확인 필요",initializing:"초기화 중",processing:"처리 중",send_to_inbox:"받은편지함 전송",publish_complete:"게시 완료",not_started:"미시작"};
    const rows=(data.items||[]).map(item=>{
      const platform=item.platform==="youtube"?"YouTube":"TikTok";
      const events=(item.events||[]).slice(-4).reverse();
      const eventHtml=events.map(event=>'<small>['+esc(event.created_at||"시간 미상")+'] '+esc(event.event_type||"event")+' · '+esc(event.outcome||"")+(event.note?' · '+esc(event.note):"")+'</small>').join("");
      const error=item.error||item.fail_reason;
      const refresh=item.platform==="tiktok"&&["processing","uploading","send_to_inbox"].includes(item.status)
        ?'<button class="button button-quiet button-small" data-pub-refresh="tiktok" data-job-id="'+esc(item.job_id)+'">원격 상태 조회</button>':"";
      const reconcile=item.reconciliation_required&&item.status!=="late_success_review_required"
        ?'<button class="button button-secondary button-small" data-pub-reconcile="'+esc(item.platform)+'" data-job-id="'+esc(item.job_id)+'">운영자 확인·조정</button>':"";
      const late=item.status==="late_success_review_required"
        ?'<small class="missing-text">지연 성공은 별도 지연 결과 해결 절차가 필요합니다. 기존 업로드 결과를 확인하세요.</small>':"";
      return '<article class="data-item"><div class="recommendation-head"><b>'+platform+' · '+esc(item.job_id||"작업 ID 없음")+'</b><strong class="'+(item.reconciliation_required||error?"missing-text":"")+'">'+esc(statusLabels[item.status]||item.status)+'</strong></div>'+
        '<small>원격 ID · '+esc(item.remote_id||"미확인")+' · 시도 '+esc(item.attempt_id||"기록 없음")+' · 갱신 '+esc(item.updated_at||"시간 미상")+'</small>'+
        (item.privacy_level?'<small>공개 범위 · '+esc(item.privacy_level)+'</small>':'')+
        (error?'<small class="missing-text">오류 · '+esc(error)+'</small>':'')+late+
        (eventHtml||'<small>감사 이벤트 없음</small>')+
        '<div class="field-row">'+refresh+reconcile+'</div></article>';
    }).join("");
    target.innerHTML=(rows||'<div class="empty-state">게시 이력이 없습니다. 이 조회는 게시를 실행하지 않습니다.</div>')+
      '<div class="notice">'+(data.limitations||[]).map(esc).join(" · ")+'</div>'+
      '<small>읽기 전용 통합 현황 · 플랫폼별 상태 독립 유지 · 감사 이벤트 최대 4건 표시</small>';
  }
  $("publishingDashboardPanel").addEventListener("click",async event=>{
    const refresh=event.target.closest("[data-pub-refresh]");
    const reconcile=event.target.closest("[data-pub-reconcile]");
    if(!refresh&&!reconcile)return;
    if(!requireToken())return;
    const button=refresh||reconcile,jobId=button.dataset.jobId;
    button.disabled=true;
    try{
      if(refresh){
        const result=await api("/api/tiktok/publications/"+encodeURIComponent(jobId)+"/refresh-status",{method:"POST"});
        toast("TikTok 원격 상태 확인 완료 · "+result.status);
      }else{
        const platform=reconcile.dataset.pubReconcile;
        const operatorId=$("reviewerInput").value.trim()||$("queueOperator").value.trim();
        const outcome=prompt(platform==="youtube"?"YouTube 결과를 확인하세요: uploaded 또는 not_uploaded":"TikTok 결과를 확인하세요: published 또는 not_published");
        if(outcome===null)return;
        const allowed=platform==="youtube"?["uploaded","not_uploaded"]:["published","not_published"];
        if(!allowed.includes(outcome.trim()))throw new Error("허용된 확인 결과를 정확히 입력하세요.");
        const videoId=outcome.trim()===(platform==="youtube"?"uploaded":"published")
          ?prompt("해당 플랫폼에서 직접 확인한 원격 영상 ID를 입력하세요."):null;
        if(videoId===null&&outcome.trim()!==(platform==="youtube"?"not_uploaded":"not_published"))return;
        const note=prompt("직접 확인한 근거와 조치 내용을 감사 메모로 입력하세요.");
        if(note===null||!note.trim())return;
        if(!confirm("원격 플랫폼에서 결과를 직접 확인했으며, 이 운영자 확인을 감사 기록에 남기시겠습니까?"))return;
        const body={outcome:outcome.trim(),confirmed:true,video_id:videoId||undefined,note:note.trim(),operator_id:operatorId};
        await api(platform==="youtube"?"/api/youtube/uploads/"+encodeURIComponent(jobId)+"/reconcile":"/api/tiktok/publications/"+encodeURIComponent(jobId)+"/reconcile",{
          method:"POST",body:JSON.stringify(body)
        });
        toast(platform+" 게시 결과 운영자 확인 기록 완료");
      }
      await loadPublishingDashboard();
    }catch(error){toast(error.message);}
    finally{button.disabled=false;}
  });
  $("loadPublishingDashboard").addEventListener("click",async()=>{
    if(!requireToken())return;
    try{await loadPublishingDashboard();toast("통합 게시 현황 갱신 완료");}
    catch(error){toast(error.message);}
  });

  async function loadPreflight(){
    const [data,tiktok]=await Promise.all([
      api("/api/preflight"),api("/api/tiktok/oauth/status")
    ]);
    const labels={operator_auth:"운영자 인증",script_generation:"AI 대본",voice_generation:"AI 음성",video_rendering:"영상 렌더링",artifact_staging:"렌더링 파일 스테이징",youtube_upload:"YouTube OAuth",youtube_data_api:"YouTube 데이터 API",tiktok_oauth:"TikTok OAuth 설정",tiktok_publish:"TikTok 비공개 게시",media_directory:"미디어 저장소"};
    const rows=Object.entries(data.checks||{}).map(([key,value])=>'<div class="data-item"><b>'+esc(labels[key]||key)+' · <span class="'+(value.configured?"ready-text":"missing-text")+'">'+(value.configured?"설정 확인":"설정 누락")+'</span></b><small>'+esc((value.missing||[]).join(", ")||"필수 설정값 존재")+'</small></div>').join("");
    const account='<div class="data-item"><b>TikTok 계정 · <span class="'+(tiktok.connected?"ready-text":"missing-text")+'">'+(tiktok.connected?"연결됨":"연결 필요")+'</span></b><small>'+esc(tiktok.open_id||tiktok.mode||tiktok.status||"OAuth 연결 후 표시")+'</small></div>';
    $("preflightList").innerHTML=rows+account+'<div class="notice"><b>'+(data.capabilities.end_to_end_configured?"필수 설정값 구성 완료":"외부 연동 설정이 더 필요합니다")+'</b><span>'+esc(data.note)+'</span></div>';
  }
  let lifecycleOffset=0;
  async function loadLifecycleQueue(){
    const filter=$("lifecycleStatusFilter")?.value||"";
    const params=new URLSearchParams({limit:"50",offset:String(lifecycleOffset)});
    if(filter)params.set("status",filter);
    const [data,performance,economics]=await Promise.all([
      api("/api/lifecycle/queue?"+params.toString()),
      api("/api/performance/pipeline?limit=100&min_samples=5"),
      api("/api/analytics/operations-economics?limit=500")
    ]);
    const counts=data.status_counts||{},productionCounts=data.production_status_counts||{},risks=data.risk_counts||{};
    const summary='<div class="finance-summary"><div><small>전체 제작 작업</small><b>'+Number(data.total||0).toLocaleString()+'</b></div><div><small>차단 위험</small><b>'+Number(risks.blocked||0).toLocaleString()+'</b></div><div><small>확인 필요</small><b>'+Number(risks.attention_required||0).toLocaleString()+'</b></div></div>';
    const rows=(data.items||[]).map(item=>{
      const findings=(item.findings||[]).slice(0,3);
      const labels={queued:"대기",running:"실행 중",review_pending:"검수 대기",approved:"승인",rejected:"반려",revision_requested:"수정 요청",failed_retriable:"재시도 대기",failed_terminal:"최종 실패",cancelled:"취소"};
      const riskLabels={blocked:"차단 조치 필요",attention_required:"운영자 확인 필요",consistent:"일관성 확인"};
      return '<article class="data-item"><div class="recommendation-head"><b>'+esc(item.brand||"브랜드 미상")+' · '+esc(item.topic||item.job_id)+'</b><strong>'+esc(riskLabels[item.risk_status]||item.risk_status)+'</strong></div><small>작업 '+esc(labels[item.status]||item.status)+' · 제작 '+esc(item.production_status||"기록 없음")+' · '+esc(item.current_stage||"단계 미상")+'</small><small>JOB '+esc(item.job_id)+' · 갱신 '+esc(item.updated_at||"")+' · 시도 '+Number(item.attempt||0)+'/'+Number(item.max_attempts||0)+'</small>'+(item.error_code?'<small class="missing-text">오류 코드: '+esc(item.error_code)+'</small>':'')+(findings.length?'<ul>'+findings.map(f=>'<li>'+esc(f.severity)+' · '+esc(f.code)+' — '+esc(f.message)+'</li>').join("")+'</ul>':'<small>현재 자동 진단된 불일치 없음</small>')+'<button class="button button-quiet button-small" data-queue-lifecycle-id="'+esc(item.job_id)+'">상세 이력·복구 진단</button></article>';
    }).join("");
    const statusSummary=Object.entries(counts).map(([status,count])=>'<span class="tag">큐 '+esc(status)+' '+Number(count).toLocaleString()+'</span>').join(" ");
    const productionSummary=Object.entries(productionCounts).map(([status,count])=>'<span class="tag">제작 '+esc(status)+' '+Number(count).toLocaleString()+'</span>').join(" ");
    const perfRows=(performance.stages||[]).map(item=>'<div class="data-item"><b>'+esc(item.stage)+' · '+esc(item.status)+'</b><small>표본 '+Number(item.sample_count)+' · 중앙값 '+(item.median_seconds===null?"표본 부족":esc(item.median_seconds+"초"))+' · P90 '+(item.p90_seconds===null?"표본 부족":esc(item.p90_seconds+"초"))+'</small></div>').join("");
    const perfHtml='<section class="review-policy"><strong>전체 파이프라인 성능 통계</strong><p>분석 작업 '+Number(performance.jobs_with_observations||0)+'/'+Number(performance.cohort_jobs||0)+' · 단계별 최소 표본 '+Number(performance.minimum_samples_per_stage||5)+'</p>'+(performance.bottleneck_candidate?'<p>병목 후보: '+esc(performance.bottleneck_candidate.stage)+' · 중앙값 '+esc(performance.bottleneck_candidate.median_seconds)+'초</p>':'<p>현재는 병목 후보를 확정할 표본이 부족합니다.</p>')+(perfRows||'<small>분석 가능한 단계별 관측치가 없습니다.</small>')+'<small>큐 상태 체류시간 기준이며 공급자 실행·렌더링 시간과 다릅니다. 최근 최대 100개 작업의 읽기 전용 통계입니다.</small></section>';
    const brandRows=(economics.brands||[]).map(item=>'<div class="data-item"><b>'+esc(item.brand)+'</b><small>작업 '+Number(item.jobs)+' · 실패율 '+(item.failure_rate_percent===null?"표본 없음":esc(item.failure_rate_percent+"%"))+' · 승인율 '+(item.approval_rate_percent===null?"검수 표본 없음":esc(item.approval_rate_percent+"%"))+' · YouTube '+Number(item.youtube_published)+' · TikTok '+Number(item.tiktok_published)+'</small></div>').join("");
    const financeRows=(economics.financial_by_currency||[]).map(item=>'<div class="data-item"><b>'+esc(item.currency)+' · 기록 매출 '+esc(item.recorded_revenue)+' · 기록 비용 '+esc(item.recorded_costs)+' · 순액 '+esc(item.recorded_net)+'</b><small>재무 기록 작업 '+Number(item.jobs_with_financial_records)+' · 비용-매출 상관 '+(item.cost_revenue_correlation.value===null?esc(item.cost_revenue_correlation.assessment):esc(item.cost_revenue_correlation.value)+' (탐색용)')+'</small></div>').join("");
    const stageFailureRows=(economics.stages||[]).map(item=>'<span class="tag">'+esc(item.stage)+' 실패율 '+(item.failure_rate_percent===null?"—":esc(item.failure_rate_percent+"%"))+' ('+Number(item.failed)+'/'+Number(item.jobs)+')</span>').join(" ");
    const economicsHtml='<section class="review-policy"><strong>제작 품질·검수·게시·기록 재무 분석</strong><p>최근 '+Number(economics.cohort_jobs||0)+'건 · 재무 연결 '+Number(economics.data_quality?.jobs_with_recorded_financials||0)+'건</p><div class="finance-summary"><div><small>브랜드별 실패·승인</small><b>'+Number((economics.brands||[]).length)+'</b></div><div><small>실패 유형</small><b>'+Object.keys(economics.failure_codes||{}).length+'</b></div><div><small>통화별 재무 집계</small><b>'+(economics.financial_by_currency||[]).length+'</b></div></div>'+(brandRows||'<small>브랜드별 집계 자료가 없습니다.</small>')+'<p><b>단계별 실패율</b></p>'+stageFailureRows+'<p><b>작업 연결 재무 기록</b></p>'+(financeRows||'<small>작업 ID에 연결된 재무 원장이 아직 없습니다. 매출은 추정하지 않습니다.</small>')+'<small>원장에 기록된 수치만 사용합니다. 통화 환산·추정 매출은 포함하지 않으며, 상관관계는 인과관계를 의미하지 않습니다.</small></section>';
    $("lifecycleQueue").innerHTML=economicsHtml+perfHtml+summary+'<div class="notice">큐 상태 '+statusSummary+'<br>제작 상태 '+productionSummary+'</div>'+(rows||'<div class="empty-state">표시할 숏폼 제작 작업이 없습니다.</div>')+'<small>읽기 전용 관제 · 자동 재시도·원격 상태 조회·게시 실행 없음 · 페이지 최대 50건 · '+(data.offset+1)+'–'+Math.min(data.offset+(data.items||[]).length,data.total)+' / '+data.total+'</small>';
    $("lifecyclePrev").disabled=data.offset<=0;
    $("lifecycleNext").disabled=data.offset+(data.items||[]).length>=data.total;
  }

  async function loadQueue(){
    const [q,w,control,health,recovery]=await Promise.all([
      api("/api/queue/stats"),api("/api/workers"),api("/api/queue/control"),api("/api/ops/health"),api("/api/ops/recovery-plan")
    ]);
    const state=control.control||{};
    $("pauseQueue").disabled=!!state.paused;
    $("resumeQueue").disabled=!state.paused;
    const status=state.paused
      ? '<span class="missing-text">중지됨</span> · '+esc(state.pause_reason||"사유 없음")
      : '<span class="ready-text">정상 운영</span>';
    const signal=(health.blockers||[]).map(x=>'<div class="data-item missing-text"><b>차단 · '+esc(x.code)+'</b><small>'+esc(x.message)+' · '+esc(x.count??"") +'</small></div>').join("")+(health.warnings||[]).map(x=>'<div class="data-item"><b>주의 · '+esc(x.code)+'</b><small>'+esc(x.message)+' · '+esc(x.count??"") +'</small></div>').join("");
    const events=(control.events||[]).slice(0,8).map(x=>'<div class="data-item"><b>'+esc(x.event_type)+' · '+esc(x.actor)+'</b><small>'+esc(x.created_at)+' · '+esc(x.reason)+'</small></div>').join("");
    $("queueDetails").innerHTML=
      '<div class="data-item"><b>생산 큐 제어 · '+status+'</b><small>중지 작업: '+esc(state.paused_job_id||"없음")+' · 갱신 '+esc(state.updated_at||"")+'</small></div>'+
      '<div class="data-item"><b>운영 안전 진단 · '+esc(health.status||"unknown")+'</b><small>작업자 '+esc(health.workers?.online??0)+' 온라인 / '+esc(health.workers?.stale??0)+' 지연 · 만료 lease '+esc(health.leases?.expired_running??0)+' · 소유권 누락 '+esc(health.leases?.running_missing_ownership??0)+'</small></div>'+'<div class="data-item"><b>복구 체크리스트 · '+esc(recovery.status||"unknown")+'</b><small>'+(recovery.operator_checks||[]).map(x=>esc(x.label)).join(" · ")+'</small></div>'+(signal||'<div class="data-item"><b>안전 신호 없음</b><small>진단 기준에서 차단·주의 항목이 발견되지 않았습니다.</small></div>')+
      '<div class="data-item"><b>Queue status</b><small>'+esc(JSON.stringify(q))+'</small></div>'+
      (w.workers||[]).map(x=>'<div class="data-item"><b>'+esc(x.worker_id)+' · '+esc(x.status)+'</b><small>'+esc(x.hostname||"")+' · '+esc(x.last_seen_at||"")+'</small></div>').join("")+
      '<h4>운영 중지·재개 감사 기록</h4>'+(events||'<div class="empty-state">아직 제어 이력이 없습니다.</div>');
  }
  async function refreshAll(){
    if(!token){setConnection(false,"인증 필요");return;}
    try{
      await Promise.all([loadMetrics(),loadFinance(),loadReviews(),loadApproved(),loadTrends(),loadTrendRecommendations(),loadSchedules(),loadInsights(),loadRecommendationExperiments(),loadOpportunities(),loadQueue(),loadLifecycleQueue(),loadPublishingDashboard(),loadPreflight()]);
      toast("운영 데이터 갱신 완료");
    }catch(e){setConnection(false,"인증·API 확인 필요");toast(e.message);}
  }
  function requireToken(){if(!token){$("settingsDialog").showModal();return false;}return true;}
  function queueControlPayload(){
    const operator_id=$("queueOperator").value.trim();
    const note=$("queueControlNote").value.trim();
    if(!operator_id||!note){toast("운영자 ID와 조치 사유를 입력하세요.");return null;}
    const recovery_confirmed=$("recoveryConfirmed").checked;
    return {operator_id,note,recovery_confirmed};
  }
  $("pauseQueue").addEventListener("click",async()=>{
    if(!requireToken())return;
    const body=queueControlPayload();if(!body)return;
    if(!confirm("숏폼 제작 큐를 중지하고 현재 실행 중인 제작 작업을 안전하게 차단하시겠습니까?"))return;
    try{
      await api("/api/queue/pause",{method:"POST",body:JSON.stringify(body)});
      toast("숏폼 제작 큐가 중지되었습니다.");await loadQueue();
    }catch(e){toast(e.message);}
  });
  $("resumeQueue").addEventListener("click",async()=>{
    if(!requireToken())return;
    const body=queueControlPayload();if(!body)return;
    if(!body.recovery_confirmed){toast("복구 체크리스트를 직접 확인하고 확인란을 선택하세요.");return;}
    if(!confirm("공급자 결과, 생성 파일·과금, 사람 승인·정책 증거 및 Worker 상태를 확인하셨습니까? 확인 후 제작 큐를 재개합니다."))return;
    try{
      await api("/api/queue/resume",{method:"POST",body:JSON.stringify(body)});
      toast("운영자 확인 기록과 함께 제작 큐가 재개되었습니다.");await loadQueue();
    }catch(e){toast(e.message);}
  });
  $("openSettings").addEventListener("click",()=>$("settingsDialog").showModal());
  $("saveToken").addEventListener("click",async()=>{
    token=$("tokenInput").value.trim();reviewer=$("reviewerInput").value.trim()||"operator";
    try{await api("/api/queue/stats");$("settingsDialog").close();msg("tokenMessage","인증 성공");await refreshAll();}
    catch(e){token="";msg("tokenMessage",e.message,true);}
  });
  $("clearToken").addEventListener("click",()=>{token="";$("tokenInput").value="";setConnection(false,"인증 필요");msg("tokenMessage","토큰이 메모리에서 초기화되었습니다.");});
  $("refreshAll").addEventListener("click",refreshAll);
  $("loadReviews").addEventListener("click",()=>loadReviews().catch(e=>toast(e.message)));
  $("loadLifecycleQueue").addEventListener("click",()=>loadLifecycleQueue().catch(e=>toast(e.message)));
  $("loadPublishingDashboard").addEventListener("click",()=>loadPublishingDashboard().catch(e=>toast(e.message)));
  $("lifecycleStatusFilter").addEventListener("change",()=>{lifecycleOffset=0;loadLifecycleQueue().catch(e=>toast(e.message));});
  $("lifecyclePrev").addEventListener("click",()=>{lifecycleOffset=Math.max(0,lifecycleOffset-50);loadLifecycleQueue().catch(e=>toast(e.message));});
  $("lifecycleNext").addEventListener("click",()=>{lifecycleOffset+=50;loadLifecycleQueue().catch(e=>toast(e.message));});
  $("lifecycleQueue").addEventListener("click",async e=>{
    const button=e.target.closest("button[data-queue-lifecycle-id]");if(!button)return;
    if(!requireToken())return;
    const id=button.dataset.queueLifecycleId;button.disabled=true;
    try{
      const overview=await api("/api/lifecycle/jobs/"+encodeURIComponent(id)+"/overview");
      const trace=overview.trace,consistency=overview.consistency,recovery=overview.recovery;
      const detail=document.createElement("div");detail.className="review-policy lifecycle-operations";
      const analysis=overview.failure?.latest_failure;
      const stageLabels={queue:"작업 큐",production:"AI 제작",human_review:"사람 검수",youtube:"YouTube",tiktok:"TikTok"};
      const stagePanel='<section class="review-policy"><strong>전체 제작 단계 현황</strong><div class="finance-summary">'+(overview.stages||[]).map(stage=>'<div><small>'+esc(stageLabels[stage.stage]||stage.stage)+'</small><b>'+esc(stage.status||"not_started")+'</b></div>').join("")+'</div><small>현재 단계: '+esc(overview.summary?.current_stage||"기록 없음")+' · 일관성: '+esc(overview.summary?.consistency_status||"unknown")+'</small></section>';
      const failurePanel=analysis?'<div class="data-item"><b>실패 원인 · '+esc(analysis.category)+' · '+esc(analysis.severity)+'</b><small>'+esc(analysis.error_code)+' · '+esc(analysis.message||"상세 오류 메시지 없음")+'</small><p>'+esc(analysis.rationale)+'</p><p><b>권장 조치:</b> '+esc(analysis.recommended_operator_action)+'</p><p><b>재처리 판정:</b> '+esc(analysis.retry_recommendation)+' (자동 재시도 권한 없음)</p></div>':'<div class="data-item"><b>실패 원인 분석</b><small>기록된 실패 이벤트가 없습니다.</small></div>';
      detail.innerHTML=stagePanel+renderLifecycleTrace(trace)+failurePanel+renderLifecycleOperations(consistency,recovery);
      button.insertAdjacentElement("afterend",detail);
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("loadSchedules").addEventListener("click",()=>loadSchedules().catch(e=>toast(e.message)));
  $("loadInsights").addEventListener("click",()=>loadInsights().catch(e=>toast(e.message)));
  $("captureRecommendationEvaluation").addEventListener("click",async()=>{
    if(!requireToken())return;
    const button=$("captureRecommendationEvaluation");
    button.disabled=true;
    try{
      const result=await api("/api/recommendations/evaluation/snapshots",{method:"POST"});
      toast(result.deduplicated?"동일 데이터의 검증 이력이 이미 저장되어 있습니다.":"검증 결과를 불변 이력으로 저장했습니다.");
      await loadInsights();
    }catch(e){toast(e.message);}
    finally{button.disabled=false;}
  });
  $("loadRecommendationExperiments").addEventListener("click",()=>loadRecommendationExperiments().catch(e=>toast(e.message)));
  $("loadRecommendationExperimentIntegrity").addEventListener("click",()=>loadRecommendationExperimentIntegrity().catch(e=>toast(e.message)));
  $("recommendationExperimentForm").addEventListener("submit",async event=>{
    event.preventDefault();
    if(!requireToken())return;
    const name=$("recommendationExperimentName").value.trim();
    if(!name)return;
    try{
      const created=await api("/api/recommendations/experiments",{method:"POST",body:JSON.stringify({
        name,operator_id:reviewer||"operator",control_label:"control",treatment_label:"treatment",
        treatment_allocation_basis_points:Number($("recommendationExperimentAllocation").value)
      })});
      $("recommendationExperimentName").value="";
      toast("Shadow 전용 실험 초안을 생성했습니다.");
      await loadRecommendationExperiments();
      await loadRecommendationExperimentReport(created.experiment_id);
    }catch(error){toast(error.message);}
  });
  $("recommendationExperimentList").addEventListener("click",async event=>{
    const shadow=event.target.closest("button[data-experiment-shadow]");
    const report=event.target.closest("button[data-experiment-report]");
    if(!shadow&&!report)return;
    if(!requireToken())return;
    const experimentId=(shadow||report).dataset.experimentShadow||(shadow||report).dataset.experimentReport;
    try{
      if(shadow){
        const result=await api("/api/recommendations/experiments/"+encodeURIComponent(experimentId)+"/shadow-assignment",{
          method:"POST",body:JSON.stringify({participant_key:createShadowParticipantKey()})
        });
        toast("샘플 배정 계산 완료 · "+result.arm+" (실제 노출 없음)");
        await loadRecommendationExperiments();
      }
      await loadRecommendationExperimentReport(experimentId);
    }catch(error){toast(error.message);}
  });
  $("loadPreflight").addEventListener("click",()=>loadPreflight().catch(e=>toast(e.message)));
  $("connectTikTok").addEventListener("click",async()=>{
    if(!requireToken())return;
    try{
      const result=await api("/api/tiktok/oauth/start");
      if(!result.authorization_url)throw new Error("TikTok OAuth authorization URL is unavailable");
      window.location.assign(result.authorization_url);
    }catch(err){toast(err.message);}
  });
  $("disconnectTikTok").addEventListener("click",async()=>{
    if(!requireToken())return;
    if(!confirm("TikTok 연결을 해제하고 TikTok 측 토큰을 폐기하시겠습니까?"))return;
    try{
      await api("/api/tiktok/oauth/disconnect",{method:"POST"});
      toast("TikTok 계정 연결이 해제되었습니다.");
      await loadPreflight();
    }catch(err){toast(err.message);}
  });
  $("productionForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const result=await api("/api/production/jobs",{method:"POST",body:JSON.stringify({brand:$("brandSelect").value,region:$("regionSelect").value,language:$("languageSelect").value,topic:$("topicInput").value.trim()})});msg("productionMessage","작업 등록 완료 · "+result.job.id);$("topicInput").value="";await refreshAll();}
    catch(err){msg("productionMessage",err.message,true);}
  });
  $("trendForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const r=await api("/api/trends/collect",{method:"POST",body:JSON.stringify({region:$("trendRegion").value,query:$("trendQuery").value.trim(),limit:Number($("trendLimit").value),include_hacker_news:true})});msg("trendList","수집 완료 · "+(r.stored??r.count??"저장 결과 확인"));await Promise.all([loadTrends(),loadTrendRecommendations()]);}
    catch(err){toast(err.message);}
  });

  $("loadTrendRecommendations").addEventListener("click",()=>loadTrendRecommendations().catch(e=>toast(e.message)));
  $("trendRecommendations").addEventListener("click",async e=>{
    const skipButton=e.target.closest("[data-recommend-skip]");
    if(skipButton){
      if(!requireToken())return;
      const selector=skipButton.parentElement.querySelector("select[data-recommend-brand]");
      if(!selector)return;
      const selectedOption=selector.selectedOptions[0];
      const candidateId=selectedOption?.dataset.candidateId;
      if(!candidateId){toast("현재 노출된 추천 후보 ID가 없습니다. 추천 목록을 새로고침하세요.");return;}
      const reason=prompt("이 추천 브랜드/주제를 제외하는 이유를 기록하세요.","브랜드 적합도 또는 중복 이슈");
      if(reason===null)return;
      skipButton.disabled=true;
      try{
        await api("/api/recommendations/feedback/skip",{
          method:"POST",
          body:JSON.stringify({
            trend_id:skipButton.dataset.recommendSkip,
            brand_slug:selector.value,
            recommendation_candidate_id:candidateId,
            reviewer_id:reviewer||"operator",
            reason
          })
        });
        toast("추천 제외 사유를 평가 데이터에 기록했습니다.");
        await loadTrendRecommendations();
      }catch(err){toast(err.message);}
      finally{skipButton.disabled=false;}
      return;
    }
    const button=e.target.closest("[data-recommend-draft]");
    if(!button)return;
    if(!requireToken())return;
    const selector=button.parentElement.querySelector("select[data-recommend-brand]");
    if(!selector)return;
    const selectedOption=selector.selectedOptions[0];
    const candidateId=selectedOption?.dataset.candidateId;
    if(!candidateId){toast("현재 노출된 추천 후보 ID가 없습니다. 추천 목록을 새로고침하세요.");return;}
    button.disabled=true;
    try{
      const result=await api("/api/trends/"+encodeURIComponent(button.dataset.recommendDraft)+"/draft-production",{
        method:"POST",body:JSON.stringify({
          brand:selector.value,
          language:button.dataset.recommendLanguage,
          recommendation_candidate_id:candidateId
        })
      });
      toast("추천 후보 제작 기획 등록 완료 · "+result.job.id);
      await Promise.all([loadMetrics(),loadTrendRecommendations()]);
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });

  $("trendList").addEventListener("click",async e=>{
    const button=e.target.closest("[data-trend-draft]");
    if(!button)return;
    if(!requireToken())return;
    const trendId=button.dataset.trendDraft;
    const selector=button.parentElement.querySelector("select[data-trend-brand]");
    if(!selector)return;
    button.disabled=true;
    try{
      const result=await api("/api/trends/"+encodeURIComponent(trendId)+"/draft-production",{
        method:"POST",body:JSON.stringify({brand:selector.value,language:button.dataset.trendLanguage})
      });
      toast("제작 기획 등록 완료 · "+result.job.id);
      await loadMetrics();
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("loadOpportunities").addEventListener("click",async()=>{
    if(!requireToken())return;
    try{await loadOpportunities();}catch(err){toast(err.message);}
  });
  $("competitorForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const r=await api("/api/competitors/search?q="+encodeURIComponent($("competitorQuery").value.trim()));$("competitorList").innerHTML=(r.channels||r.items||[]).map(x=>'<div class="data-item competitor-item"><b>'+esc(x.title||x.name||x.channel_title||x.channel_id)+'</b><small>'+esc(x.custom_url||x.channel_id||"")+' · '+esc(x.subscriber_count??"subscriber count hidden")+'</small><div class="competitor-actions"><label><input type="checkbox" data-competitor-select value="'+esc(x.channel_id)+'"> 점수 비교에 포함</label><button type="button" class="button button-quiet button-small" data-inspect-channel="'+esc(x.channel_id)+'">최근 영상 분석</button></div><div class="competitor-evidence" id="competitor-'+esc(x.channel_id)+'"></div></div>').join("")||'<div class="empty-state">검색 결과가 없습니다.</div>';}
    catch(err){toast(err.message);}
  });
  $("competitorList").addEventListener("click",async e=>{
    const button=e.target.closest("[data-inspect-channel]");if(!button)return;
    if(!requireToken())return;
    const id=button.dataset.inspectChannel;button.disabled=true;
    try{
      const data=await api("/api/competitors/"+encodeURIComponent(id)+"?video_limit=20");
      const target=$("competitor-"+CSS.escape(id));
      target.innerHTML='<small>저장된 최근 영상 '+(data.recent_videos||[]).length+'개 · 조회수는 수집 시점의 공개 카운터입니다.</small>'+
        (data.recent_videos||[]).slice(0,5).map(v=>'<div class="competitor-video"><span>'+esc(v.title)+'</span><b>'+esc(v.view_count??"비공개")+' views</b></div>').join("");
      toast("최근 영상 표본을 저장했습니다. 점수 평가 시 선택 채널의 주제 유사도를 계산합니다.");
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("opportunityForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    const num=id=>Number($(id).value);
    const body={title:$("oppTitle").value,currency:$("oppCurrency").value,forecast_source:$("forecastSource").value,forecast_views_low:num("viewsLow"),forecast_views_high:num("viewsHigh"),rpm_low:num("rpmLow"),rpm_high:num("rpmHigh"),cost_low:num("costLow"),cost_high:num("costHigh"),monetization_eligible:$("monetizationEligible").checked,competitor_channel_ids:Array.from(document.querySelectorAll("[data-competitor-select]:checked")).map(x=>x.value)};
    try{const r=await api("/api/opportunities/score",{method:"POST",body:JSON.stringify(body)});const market=r.competitive_context||{};msg("opportunityResult","우선순위 점수 "+r.priority_score+" / 100 · 비교 표본 "+market.observed_videos+"개 · 주제 유사 "+market.topic_matched_videos+"개 · 경쟁 조정 "+(market.score_adjustment??0)+"점. "+(market.method||"경쟁 표본 미선택")+". 예상치이며 실제 수익이 아닙니다.");await loadOpportunities();}
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
      }else if(action==="policy-evidence"){
        const synthetic=prompt(
          "실제 생성된 영상의 유형을 선택해 입력하세요: none / ai_assisted_nonrealistic / ai_generated / realistic_alteration",
          "ai_generated"
        );
        if(synthetic===null)return;
        if(!["none","ai_assisted_nonrealistic","ai_generated","realistic_alteration"].includes(synthetic.trim())) {
          toast("지원하지 않는 합성 미디어 유형입니다.");return;
        }
        const hasCommercialRelationship=confirm("이 콘텐츠에 협찬·제휴·유료 파트너십 등 상업적 관계가 있습니까?");
        const commercialRelationshipDisclosed=!hasCommercialRelationship||confirm("해당 상업적 관계를 영상과 설명에 명확히 표시했습니까?");
        const declarations={
          reviewer_id:reviewer,
          platforms:["youtube","tiktok"],
          rights:{
            visuals_cleared:confirm("영상·이미지 등 시각 자료의 사용 권리가 확인되었습니까?"),
            audio_cleared:confirm("음악·효과음·음성 등 오디오 권리가 확인되었습니까?"),
            likeness_authorized:confirm("식별 가능한 인물의 초상·음성 사용 권한이 있거나 해당 인물이 포함되지 않습니까?")
          },
          synthetic_media_status:synthetic.trim(),
          factual_claims_verified:confirm("대본의 사실·통계·인용 주장을 신뢰할 수 있는 자료로 검증했습니까?"),
          commercial_relationship_disclosed:commercialRelationshipDisclosed,
          originality_notes:prompt("이번 영상만의 독창적인 설명·분석·구성 차이를 기록하세요.","독창적 설명과 편집 구성을 검토함")||""
        };
        if(["ai_generated","realistic_alteration"].includes(declarations.synthetic_media_status)){
          declarations.platform_disclosures={
            youtube_altered_content:confirm("YouTube 업로드 시 실제와 같이 보이는 AI 생성·변형 콘텐츠 표시를 적용할 준비가 되었습니까?"),
            tiktok_ai_generated_content:confirm("TikTok 게시 시 AI 생성 콘텐츠 라벨을 적용할 준비가 되었습니까?")
          };
        }
        const result=await api("/api/review/"+encodeURIComponent(id)+"/policy-evidence",{
          method:"POST",body:JSON.stringify(declarations)
        });
        toast("정책 정보가 감사 기록과 함께 저장되었습니다 · "+result.policy_preflight.status);
        await loadReviews();
      }else{
        let comment;
        if(action==="approve"){
          const policyStatus=b.dataset.policyStatus||"missing";
          const qualityStatus=b.dataset.qualityStatus||"missing";
          comment=(policyStatus==="review_required"||qualityStatus==="review_required")
            ? prompt("정책·품질 경고를 실제 자료로 확인한 뒤 근거를 승인 메모에 기록하세요. 정책: "+(b.dataset.policyRequired||"없음")+" / 품질: "+(b.dataset.qualityWarnings||"없음"),"영상·음성·자막·대본 및 정책 경고를 실제 자료로 확인 완료")
            : "Approved after human review";
          if(comment===null||!String(comment).trim())return;
        }else{
          comment=prompt(action==="reject"?"반려 사유":"수정 요청 내용");
          if(comment===null)return;
        }
        const endpoint=action==="approve"?"approve":action==="reject"?"reject":"request-revision";
        await api("/api/review/"+encodeURIComponent(id)+"/"+endpoint,{method:"POST",body:JSON.stringify({reviewer_id:reviewer,comment})});
        toast("검수 결정이 기록되었습니다.");await refreshAll();
      }
    }catch(err){toast(err.message);}
  });

  $("approvedList").addEventListener("click",async e=>{
    const lifecycleButton=e.target.closest("button[data-lifecycle-id]");
    if(lifecycleButton){
      if(!requireToken())return;
      const id=lifecycleButton.dataset.lifecycleId;
      lifecycleButton.disabled=true;
      try{
        const overview=await api("/api/lifecycle/jobs/"+encodeURIComponent(id)+"/overview");
        const target=$("lifecycle-"+id);
        if(target)target.innerHTML=renderLifecycleTrace(overview.trace,overview.performance)+
          '<section class="review-policy"><strong>통합 운영 상태</strong><p>일관성 · '+esc(overview.summary?.consistency_status||"unknown")+
          ' · 실패 유형 · '+esc(overview.summary?.failure_category||"없음")+'</p></section>'+
          renderLifecycleOperations(overview.consistency,overview.recovery);
      }catch(err){
        const target=$("lifecycle-"+id);
        if(target)target.textContent=err.message;
        toast(err.message);
      }finally{lifecycleButton.disabled=false;}
      return;
    }
    const tiktokRefresh=e.target.closest("button[data-tiktok-refresh-id]");
    if(tiktokRefresh){
      if(!requireToken())return;
      const id=tiktokRefresh.dataset.tiktokRefreshId;
      tiktokRefresh.disabled=true;
      try{
        const result=await api("/api/tiktok/publications/"+encodeURIComponent(id)+"/refresh-status",{method:"POST"});
        toast("TikTok 상태 갱신 · "+result.status);
        await refreshAll();
      }catch(err){
        $("upload-"+CSS.escape(id)).textContent=err.message;
        toast(err.message);
      }finally{tiktokRefresh.disabled=false;}
      return;
    }
    const tiktokPublish=e.target.closest("button[data-tiktok-publish-id]");
    if(tiktokPublish){
      if(!requireToken())return;
      const id=tiktokPublish.dataset.tiktokPublishId;
      tiktokPublish.disabled=true;
      try{
        const creator=await api("/api/tiktok/creator-info");
        const options=creator.privacy_level_options||[];
        if(!options.includes("SELF_ONLY")){
          throw new Error("이 TikTok 계정은 SELF_ONLY 비공개 게시를 지원하지 않습니다.");
        }
        const account=creator.creator_nickname||creator.creator_username||"연결된 TikTok 계정";
        const privacySummary=options.join(", ");
        if(!confirm(account+" 계정의 TikTok 공개 범위 옵션: "+privacySummary+"\nNEXUS 현재 운영 모드는 SELF_ONLY 비공개 전송으로 제한됩니다."))return;
        const selectedPrivacy=prompt("TikTok 공개 범위를 직접 선택하세요. 현재 앱은 미감사 상태이므로 SELF_ONLY만 허용됩니다. 정확히 입력하세요: SELF_ONLY");
        if(selectedPrivacy===null)return;
        if(selectedPrivacy.trim()!=="SELF_ONLY"){toast("현재 허용되는 공개 범위는 SELF_ONLY뿐입니다.");return;}
        const caption=prompt("TikTok 캡션을 입력하세요. 최대 2,200 UTF-16 코드 단위입니다.", "NEXUS STUDIO PRO · "+id.slice(0,8));
        if(caption===null)return;
        const title=caption.trim();
        if(!title){toast("TikTok 캡션을 입력하세요.");return;}
        const brandContent=confirm("이 콘텐츠가 제3자 브랜드의 유료 파트너십 또는 협찬을 홍보합니까?");
        const brandOrganic=confirm("이 콘텐츠가 크리에이터 본인의 사업·브랜드를 홍보합니까?");
        const staged=await api("/api/production/jobs/"+encodeURIComponent(id)+"/stage-media",{method:"POST"});
        const result=await api("/api/tiktok/publish/"+encodeURIComponent(id),{
          method:"POST",
          body:JSON.stringify({
            media_path:staged.media_path,
            title,
            operator_id:reviewer||"operator",
            privacy_level:selectedPrivacy.trim(),
            explicit_consent:true,
            brand_content_toggle:brandContent,
            brand_organic_toggle:brandOrganic
          })
        });
        $("upload-"+CSS.escape(id)).textContent="TikTok 미디어 전송 완료 · "+result.status+" · 상태 확인을 기다립니다.";
        toast("TikTok 비공개 게시 요청을 전송했습니다. 완료 상태를 확인합니다.");
        await refreshAll();
      }catch(err){
        $("upload-"+CSS.escape(id)).textContent=err.message;
        toast(err.message);
      }finally{tiktokPublish.disabled=false;}
      return;
    }
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
  const tiktokOAuthResult=new URLSearchParams(window.location.search).get("tiktok_oauth");
  if(tiktokOAuthResult==="connected")toast("TikTok 계정 연결 및 토큰 저장이 완료되었습니다.");
  else if(tiktokOAuthResult==="denied")toast("TikTok 계정 연결이 취소되었거나 거부되었습니다.");
  else if(tiktokOAuthResult==="error")toast("TikTok 계정 연결에 실패했습니다. 설정과 로그를 확인하세요.");
  if(tiktokOAuthResult)window.history.replaceState({}, "", window.location.pathname);
  loadBrands().then(()=>{setConnection(false,"API 인증 필요");}).catch(e=>setConnection(false,"API 연결 실패: "+e.message));
})();