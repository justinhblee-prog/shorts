(() => {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let reviewer = "operator";
  let brands = [];
  let toastTimer;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  function safeExternalMediaUrl(value){
    if(typeof value!=="string"||!value.trim())return "";
    try{
      const url=new URL(value);
      if(url.protocol!=="https:"||url.username||url.password)return "";
      return url.href;
    }catch{return "";}
  }
  function retentionCheckpoint(points,target){
    const valid=(Array.isArray(points)?points:[]).filter(p=>p&&Number.isFinite(Number(p.elapsed_video_time_ratio))&&Number.isFinite(Number(p.audience_watch_ratio)));
    if(!valid.length)return "—";
    const point=valid.reduce((best,item)=>Math.abs(Number(item.elapsed_video_time_ratio)-target)<Math.abs(Number(best.elapsed_video_time_ratio)-target)?item:best);
    return Number(point.audience_watch_ratio).toFixed(2)+"x";
  }
  function retentionSummary(points){
    if(!Array.isArray(points)||!points.length)return "데이터 없음";
    return [0.25,0.50,0.75].map((ratio,index)=>[25,50,75][index]+"% "+retentionCheckpoint(points,ratio)).join(" · ");
  }
  function retentionSparkline(points){
    const valid=(Array.isArray(points)?points:[]).filter(p=>p&&Number.isFinite(Number(p.elapsed_video_time_ratio))&&Number.isFinite(Number(p.audience_watch_ratio))).sort((a,b)=>Number(a.elapsed_video_time_ratio)-Number(b.elapsed_video_time_ratio));
    if(valid.length<2)return "";
    const maxValue=Math.max(1,...valid.map(p=>Number(p.audience_watch_ratio)));
    const coordinates=valid.map(p=>{
      const x=Math.max(0,Math.min(100,Number(p.elapsed_video_time_ratio)*100));
      const y=28-(Math.max(0,Math.min(maxValue,Number(p.audience_watch_ratio)))/maxValue)*26;
      return x.toFixed(2)+","+y.toFixed(2);
    }).join(" ");
    return '<svg viewBox="0 0 100 30" role="img" aria-label="YouTube audience retention curve" style="width:120px;height:30px;vertical-align:middle"><polyline fill="none" stroke="currentColor" stroke-width="2" points="'+coordinates+'"></polyline></svg>';
  }
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
      const videoUrl=safeExternalMediaUrl(video?.artifact_url);
      const recoveryAttempt=video?.metadata?.recovered_from_provider_attempt;
      const recoveryFingerprint=video?.metadata?.media_staging||{};
      const recoverySummary=recoveryAttempt
        ? '<section class="review-policy"><strong>외부 AI 생성 결과 복구</strong>'
          +'<p>공급자 실행 기록: '+esc(recoveryAttempt)+'</p>'
          +'<p>검증 파일 SHA-256: <code>'+esc(recoveryFingerprint.sha256||"기록 없음")+'</code></p>'
          +'<p>파일 크기: '+esc(recoveryFingerprint.size_bytes||"알 수 없음")+' bytes · 경로: '+esc(recoveryFingerprint.media_path||"기록 없음")+'</p>'
          +'<small>기존 공급자 응답에서 복구한 결과입니다. 파일 검사와 품질 게이트를 통과했더라도 사람의 최종 검수 및 별도 승인 전에는 게시할 수 없습니다.</small></section>'
        : '';
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
      const audioUrl=safeExternalMediaUrl(audioArtifact?.artifact_url);
      const audioPreview=audioUrl
        ? '<div class="review-audio"><label>내레이션 미리 듣기</label><audio controls preload="metadata" src="'+esc(audioUrl)+'"></audio></div>'
        : '';
      const profile=item.brand_profile||{};
      const rules=Array.isArray(profile.review_rules)?profile.review_rules:[];
      const guidance=profile.risk_level
        ? '<section class="review-guidance"><div><strong>브랜드 검수 기준</strong><span class="risk-level risk-'+esc(profile.risk_level)+'">위험도 '+esc(profile.risk_level)+'</span></div>'+(profile.positioning?'<p>'+esc(profile.positioning)+'</p>':'')+(rules.length?'<ul>'+rules.map(rule=>'<li>'+esc(rule)+'</li>').join('')+'</ul>':'')+'</section>'
        : '';
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · '+esc(item.current_stage||item.status)+'</p><div class="review-meta">JOB '+esc(item.job_id)+' · '+esc(item.updated_at||"")+'</div>'+recoverySummary+guidance+policySummary+qualitySummary+scriptPreview+audioPreview+(videoUrl?'<p><a target="_blank" rel="noopener noreferrer" href="'+esc(videoUrl)+'">렌더링 영상 열기 ↗</a></p>':'')+'<div class="inline-message" id="stage-'+esc(item.job_id)+'"></div></div><div class="review-actions"><button class="button button-quiet" data-action="stage" data-id="'+esc(item.job_id)+'">미디어 스테이징</button><button class="button button-primary" data-action="approve" data-id="'+esc(item.job_id)+'" data-policy-status="'+esc(policy.status||"missing")+'" data-policy-required="'+esc(policyItems.join(", "))+'" data-policy-blockers="'+esc(policyApprovalBlocks.join(", "))+'" data-quality-status="'+esc(quality.status||"missing")+'" data-quality-warnings="'+esc(qualityWarnings.join(", "))+'" '+((policyApprovalBlocks.length||qualityBlocks.length)?'disabled title="필수 정책 또는 품질 차단 항목 해결 전 승인할 수 없습니다"':'')+'>승인</button><button class="button button-outline" data-action="revision" data-id="'+esc(item.job_id)+'">수정 요청</button><button class="button button-quiet" data-action="reject" data-id="'+esc(item.job_id)+'">반려</button></div></article>';
    }).join(""):'<div class="empty-state">현재 검수 대기 콘텐츠가 없습니다.</div>';
  }

  async function loadApproved(){
    const data=await api("/api/review/approved?limit=100");
    const items=data.items||[];
    $("approvedList").innerHTML=items.length?items.map(item=>{
      const video=(item.artifacts||[]).find(a=>a.artifact_type==="video");
      const videoUrl=safeExternalMediaUrl(video?.artifact_url);
      const uncertain=!!item.upload_reconciliation_required;
      const status=item.upload_status||"not_uploaded";
      const tiktokStatus=item.tiktok_status||"not_published";
      const tiktokUncertain=!!item.tiktok_reconciliation_required;
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
      const tiktokAction=tiktokStatus==="publish_complete"
        ? '<button class="button button-quiet" disabled>TikTok 게시 완료</button>'
        : (tiktokStatus==="send_to_inbox"
          ? '<button class="button button-quiet" disabled>TikTok 앱에서 게시 완료 필요</button>'
          : (tiktokUncertain
            ? '<button class="button button-outline" data-tiktok-reconcile-id="'+esc(item.job_id)+'">TikTok 결과 대조</button>'
            : (["initializing","uploading","processing"].includes(tiktokStatus)
              ? '<button class="button button-quiet" data-tiktok-refresh-id="'+esc(item.job_id)+'">TikTok 상태 확인</button>'
              : '<button class="button button-secondary" data-tiktok-publish-id="'+esc(item.job_id)+'">TikTok 비공개 게시</button>')));
      const tiktokStatusText=tiktokStatus==="publish_complete"?"TikTok 게시 완료":
        (tiktokUncertain?"TikTok 게시 결과 확인 필요":
        (["initializing","uploading","processing"].includes(tiktokStatus)?"TikTok 처리 중":
        (tiktokStatus==="send_to_inbox"?"TikTok 앱에서 게시 완료 필요":
        (tiktokStatus==="failed"?"TikTok 이전 시도 실패":"TikTok 게시 대기"))));
      const tiktokIdSummary=item.tiktok_video_id?'<p>TikTok 영상 ID: '+esc(item.tiktok_video_id)+'</p>':"";
      const statusText=status==="late_success_review_required"?"늦은 업로드 성공 · 운영자 확인 필요":(uncertain?"업로드 결과 확인 필요":(status==="uploading"?"업로드 진행 중":(status==="failed"?"이전 업로드 실패 · 재시도 가능":(status==="uploaded"?"업로드 완료":"업로드 대기"))));
      return '<article class="review-card"><div><h4>'+esc(item.brand)+' · '+esc(item.topic)+'</h4><p>'+esc(item.region)+' / '+esc(item.language)+' · 승인 완료 · '+esc(statusText)+'</p><p>'+esc(tiktokStatusText)+'</p><div class="review-meta">JOB '+esc(item.job_id)+'</div>'+(videoUrl?'<p><a target="_blank" rel="noopener noreferrer" href="'+esc(videoUrl)+'">원본 영상 열기 ↗</a></p>':'')+existingIdSummary+lateIdSummary+tiktokIdSummary+'<div class="inline-message" id="upload-'+esc(item.job_id)+'"></div></div><div class="review-actions">'+action+tiktokAction+'</div></article>';
    }).join(""):'<div class="empty-state">승인 완료 후 업로드 대기 중인 콘텐츠가 없습니다.</div>';
  }
  async function loadYouTubeConnection(){
    try{
      const data=await api("/api/youtube/oauth/status");
      const connected=!!data.connected;
      const scopeLabel=data.scopes&&data.scopes.length?" · "+data.scopes.join(", "):"";
      const mode=data.mode==="environment_refresh_token"?"환경 토큰(권한 목록 확인 불가)":"암호화 OAuth";
      $("youtubeConnectionStatus").textContent=connected
        ? "OAuth 승인·토큰 저장됨 · "+(data.channel_title?data.channel_title+" · ":"")+(data.data_api_verified?"Data API 확인":"Data API 미검증")+" · "+(data.analytics_api_verified?"Analytics 확인":"Analytics 미검증")+" · "+mode+scopeLabel
        : "연결 필요 · YouTube 업로드와 Analytics 권한 승인 필요";
      const managed=data.mode==="encrypted_oauth"&&connected;
      $("youtubeConnect").textContent=managed?"YouTube OAuth 연결됨":(data.mode==="encrypted_oauth"?"YouTube 권한 재승인":(connected?"암호화 OAuth로 전환":"YouTube 계정 연결"));
      $("youtubeConnect").disabled=managed;
      $("youtubeDisconnect").disabled=!managed||!!data.static_fallback_configured;
      $("youtubeVerify").disabled=!managed;
    }catch(err){
      $("youtubeConnectionStatus").textContent="연결 설정 확인 필요 · "+err.message;
      $("youtubeConnect").textContent="YouTube 연결";
      $("youtubeConnect").disabled=false;
      $("youtubeDisconnect").disabled=true;
      $("youtubeVerify").disabled=true;
    }
  }

  async function loadTikTokConnection(){
    try{
      const data=await api("/api/tiktok/oauth/status");
      const connected=!!data.connected;
      $("tiktokConnectionStatus").textContent=connected
        ? "연결됨 · "+(data.mode||"OAuth")
        : "연결 필요 · OAuth 인증 후 비공개 게시 가능";
      $("tiktokConnect").textContent=connected?"TikTok 연결됨":"TikTok 계정 연결";
      $("tiktokConnect").disabled=connected;
    }catch(err){
      $("tiktokConnectionStatus").textContent="연결 설정 확인 필요 · "+err.message;
      $("tiktokConnect").textContent="TikTok 연결";
      $("tiktokConnect").disabled=false;
    }
  }

  async function loadTikTokMetrics(){
    try{
      const data=await api("/api/tiktok/metrics?limit=20");
      const items=data.items||[];
      $("tiktokMetrics").innerHTML=items.length?items.map(item=>
        '<div class="data-item"><b>'+esc(item.title||item.video_id||"TikTok video")+'</b>'+
        '<small>조회 '+Number(item.view_count||0).toLocaleString()+
        ' · 좋아요 '+Number(item.like_count||0).toLocaleString()+
        ' · 댓글 '+Number(item.comment_count||0).toLocaleString()+
        ' · 공유 '+Number(item.share_count||0).toLocaleString()+'</small></div>'
      ).join(""):'<div class="empty-state">아직 수집된 TikTok 성과가 없습니다. 게시 후 수집 주기를 기다리거나 상태를 갱신하세요.</div>';
    }catch(err){
      $("tiktokMetrics").innerHTML='<div class="empty-state">'+esc(err.message)+'</div>';
    }
  }

  async function loadRecommendationEvaluation(){
    const platform=$("trendPlatform").value;
    const data=await api("/api/recommendations/evaluation?platform="+encodeURIComponent(platform));
    const within=data.within_run_validation||{};
    $("recommendationEvaluation").innerHTML=
      '<b>'+esc(platform==="tiktok"?"TikTok":"YouTube Shorts")+' · '+esc(within.status||"insufficient_data")+'</b>'+
      '<span>노출 실행 '+Number(within.eligible_run_count||0)+'회 · 비교 코호트 '+Number(within.eligible_cohort_count||0)+'개 · 측정 결과 '+Number(data.measured_outcome_count||0)+'건</span>'+
      '<span>'+esc(within.reason||data.warning||"비교 데이터가 충분하지 않습니다.")+'</span>'+
      '<span>자동 점수 조정: 비활성 · 실제 운영 데이터 기반의 추가 검증 필요</span>';
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

  async function loadTrendRecommendations(){
    const region=$("trendRegion").value;
    const platform=$("trendPlatform").value;
    const data=await api("/api/trends/recommendations/snapshot?region="+encodeURIComponent(region)+"&limit=20&platform="+encodeURIComponent(platform),{method:"POST"});
    const items=data.items||[];
    $("trendRecommendations").innerHTML=items.map(item=>{
      const trend=item.trend||{};
      const candidates=item.brand_candidates||[];
      const language=region==="KR"?"ko":(region==="JP"?"ja":"en");
      const options=candidates.filter(x=>(x.supported_languages||[]).includes(language))
        .map(x=>'<option value="'+esc(x.brand)+'">'+esc(x.brand_name)+'</option>').join("");
      const controls=trend.id&&options
        ? '<div class="trend-actions"><select aria-label="추천 제작 브랜드" data-recommend-brand="'+esc(trend.id)+'">'+options+'</select><button type="button" class="button button-secondary" data-recommend-draft="'+esc(trend.id)+'" data-recommend-language="'+language+'" data-recommend-platform="'+platform+'" data-recommend-run="'+esc(data.evaluation_run_id||"")+'">추천 브랜드로 기획</button></div>'
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
        ? '<small>동일 주제·시장 실측 '+Number(topicHistory.matched_video_count)+'개 · 시간당 조회 증가 중앙값 '+(topicHistory.median_views_per_hour===null||topicHistory.median_views_per_hour===undefined?"—":Number(topicHistory.median_views_per_hour).toLocaleString())+' · 1,000회당 상호작용 '+(topicHistory.median_interactions_per_1000_view_delta===null?'—':Number(topicHistory.median_interactions_per_1000_view_delta).toFixed(1))+'</small>'
        : '<small>동일 주제·시장 실측 '+Number(topicHistory.matched_video_count||0)+'개 · 추천 점수 미반영(최소 3개 표본 필요)</small>';
      const topicAnalyticsSummary=[
        topicHistory.median_engaged_view_share===null||topicHistory.median_engaged_view_share===undefined?null:'참여 조회 비율 중앙값 '+(Number(topicHistory.median_engaged_view_share)*100).toFixed(1)+'%',
        topicHistory.median_average_view_percentage===null||topicHistory.median_average_view_percentage===undefined?null:'평균 시청 비율 중앙값 '+Number(topicHistory.median_average_view_percentage).toFixed(1)+'%',
        topicHistory.median_average_view_duration_seconds===null||topicHistory.median_average_view_duration_seconds===undefined?null:'평균 시청 시간 중앙값 '+Number(topicHistory.median_average_view_duration_seconds).toFixed(1)+'초',
        ...Object.entries(topicHistory.audience_retention_samples||{}).map(([key,value])=>value.median_audience_watch_ratio===null||value.median_audience_watch_ratio===undefined?null:key.replace("audience_watch_ratio_","")+ '% 구간 유지율 지표 '+Number(value.median_audience_watch_ratio).toFixed(2))
      ].filter(Boolean).join(' · ');
      const cohortContext=item.best_brand?.comparable_cohort_performance||{};
      const cohortRows=(cohortContext.cohorts||[]).slice(0,2);
      const cohortSummary=cohortRows.length
        ? '<small>비교 코호트 · '+cohortRows.map(x=>esc(x.publication_age_bucket)+' / '+esc(x.duration_bucket)+' · '+Number(x.sample_count)+'개 · '+Number(x.median_views_per_hour||0).toLocaleString()+' views/hour').join(' | ')+'</small>'
        : '<small>동일 브랜드·시장·주제의 비교 코호트 표본 부족</small>';
      return '<div class="data-item trend-item"><div class="recommendation-head"><b>'+esc(trend.title||"Untitled trend")+'</b><strong>'+Number(item.recommendation_score||0).toFixed(1)+'/100</strong></div><small>'+esc(trend.region||"")+' · 최신성 '+Number(item.freshness_score||0).toFixed(1)+' · '+esc(item.score_type||"")+'</small>'+(item.best_brand?'<small>최적 브랜드: '+esc(item.best_brand.brand_name)+' · 적합도 '+Number(item.best_brand.fit_score||0).toFixed(1)+'</small>':'<small>적합 브랜드 미확인</small>')+topicHistorySummary+(topicAnalyticsSummary?'<small>'+esc(topicAnalyticsSummary)+' · Analytics 실측</small>':'')+cohortSummary+historySummary+competitorSummary+controls+'<small class="recommendation-caveat">과거 실측값은 동일 브랜드·시장·주제 및 게시 경과·영상 길이별 비교 표본을 별도로 표시하며, 현재 추천 점수에는 반영되지 않습니다. 경쟁 지표도 저장된 최대 10개 채널의 최근 영상 표본으로 시장 전체 수요나 수익을 뜻하지 않습니다.</small></div>';
    }).join("")||'<div class="empty-state">선택한 시장에 추천할 트렌드가 없습니다.</div>';
  }

  async function loadSchedules(){
    const [data,outbox]=await Promise.all([api("/api/schedules"),api("/api/schedules/outbox")]);
    const schedules=(data.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.name)+' · '+(x.active?"활성":"중지")+'</b><small>'+esc(x.payload.brand)+' · '+esc(x.payload.region)+' · '+esc((x.payload.platforms||["youtube"])[0])+' · 다음 실행 '+esc(x.next_run_at)+'</small></div>').join("")||'<div class="empty-state">등록된 예약이 없습니다.</div>';
    const counts=outbox.counts||{};
    const dispatches=(outbox.items||[]).map(x=>'<div class="data-item"><b>'+esc(x.status)+' · '+esc(x.schedule_id)+'</b><small>'+esc(x.scheduled_for)+' · 실패 '+Number(x.attempts||0)+'회'+(x.next_attempt_at?' · 다음 재시도 '+esc(x.next_attempt_at):'')+(x.last_error?' · '+esc(x.last_error):'')+'</small>'+(x.status==="dead_letter"?'<button class="button button-secondary button-small" type="button" data-schedule-outbox-retry="'+esc(x.id)+'">수동 재시도</button>':'')+'</div>').join("");
    $("scheduleList").innerHTML='<div class="notice">즉시 실행 가능 '+Number(outbox.pending_ready||0)+' · 재시도 대기 '+Number(outbox.pending_retries||0)+' · 격리 '+Number(counts.dead_letter||0)+' · 전달 완료 '+Number(counts.dispatched||0)+'</div>'+schedules+'<h4>예약 실행 복구 로그</h4>'+(dispatches||'<div class="empty-state">예약 실행 이력이 없습니다.</div>');
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
    const [data,evaluation,analyticsCollection]=await Promise.all([
      api("/api/performance/insights"),
      api("/api/recommendations/evaluation"),
      api("/api/youtube/analytics/collection-status")
    ]);
    const brands=(data.brands||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+Number(x.view_delta||0).toLocaleString()+' views (snapshot delta)</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+' · 평균 시청 시간 중앙값 '+(x.median_average_view_duration_seconds===null||x.median_average_view_duration_seconds===undefined?"—":Number(x.median_average_view_duration_seconds).toFixed(1)+"초")+' · 평균 시청 비율 '+(x.median_average_view_percentage===null||x.median_average_view_percentage===undefined?"—":Number(x.median_average_view_percentage).toFixed(1)+"%")+' · 참여 조회 비율 중앙값 '+(x.median_engaged_view_share===null||x.median_engaged_view_share===undefined?"—":(Number(x.median_engaged_view_share)*100).toFixed(1)+"%")+' · Analytics 실측 '+Number(x.analytics_measured_videos||0)+'개</small><small>미측정 '+x.unmeasured_videos+' · '+esc((x.recommendations||[]).map(r=>r.action).join(" / "))+'</small></div>').join("");
    const regions=(data.regions||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+Number(x.view_delta||0).toLocaleString()+' views</b><small>측정 영상 '+x.measured_videos+'/'+x.videos+'</small></div>').join("");
    const videos=(data.videos||[]).map(x=>{
      const curve=x.audience_retention_curve||[];
      const diagnostics=x.retention_diagnostics||{};
      const drop=diagnostics.largest_dropoff;
      const observations=(x.analytics_observations||[]).map(item=>item.action).join(" · ");
      const dropSummary=drop?Number(drop.start_video_ratio*100).toFixed(0)+"–"+Number(drop.end_video_ratio*100).toFixed(0)+"% 구간에서 "+Number(drop.drop_percentage_points).toFixed(1)+"%p 하락":"뚜렷한 인접 구간 하락 없음/표본 부족";
      return '<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic)+'</b><small>'+esc(x.measurement_status)+' · snapshots '+x.snapshot_count+(x.view_delta===undefined?"":" · Δ "+Number(x.view_delta).toLocaleString())+' · 참여 조회 비율 '+(x.engaged_view_share===null||x.engaged_view_share===undefined?"—":(Number(x.engaged_view_share)*100).toFixed(1)+"%")+' · 평균 시청 '+(x.average_view_duration_seconds===null||x.average_view_duration_seconds===undefined?"—":Number(x.average_view_duration_seconds).toFixed(1)+"초")+' · 평균 시청 비율 '+(x.average_view_percentage===null||x.average_view_percentage===undefined?"—":Number(x.average_view_percentage).toFixed(1)+"%")+'</small><small>구간별 시청 비율: '+esc(retentionSummary(curve))+'</small><small>최대 관측 이탈: '+esc(dropSummary)+'</small>'+(observations?'<small>비교 관측: '+esc(observations)+' · 순위 점수 변경 없음</small>':"")+(curve.length>1?'<div class="retention-curve">'+retentionSparkline(curve)+'</div>':'')+'<small>'+esc(x.analytics_status||"not_collected")+' · 유지율 표본 '+Number(curve.length)+'점</small>'+(x.video_id?'<button type="button" class="button button-quiet" data-youtube-analytics-refresh="'+esc(x.video_id)+'">Analytics 갱신</button>':"")+'</div>';
    }).join("");
    const cohorts=(data.cohorts||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic_signature)+' · '+esc(x.duration_bucket)+' · '+esc(x.publication_age_bucket)+'</b><small>'+esc(x.format)+' · 비교 표본 '+Number(x.sample_count||0)+'개 · 중앙값 '+Number(x.median_views_per_hour||0).toLocaleString()+' views/hour · '+esc(x.evidence_status)+' · 추천 점수 반영 안 함</small></div>').join("");
    const analyticsCohorts=(data.analytics_cohorts||[]).map(x=>{
      const percentage=x.metrics?.average_view_percentage||{};
      const duration=x.metrics?.average_view_duration_seconds||{};
      const engaged=x.metrics?.engaged_view_share||{};
      return '<div class="data-item"><b>'+esc(x.brand)+' / '+esc(x.region)+' · '+esc(x.topic_signature)+'</b><small>'+esc(x.duration_bucket)+' · '+esc(x.publication_age_bucket)+' · '+esc(x.format)+' · 비교 영상 '+Number(x.video_count||0)+'개 · '+esc(x.evidence_status)+'</small><small>평균 시청 비율 중앙값 '+(percentage.median===null||percentage.median===undefined?"—":Number(percentage.median).toFixed(1)+"%")+' ('+Number(percentage.sample_count||0)+'개) · 평균 시청 시간 '+(duration.median===null||duration.median===undefined?"—":Number(duration.median).toFixed(1)+"초")+' · 참여 조회 비율 '+(engaged.median===null||engaged.median===undefined?"—":(Number(engaged.median)*100).toFixed(1)+"%")+' · 추천 점수 반영 안 함</small></div>';
    }).join("");
    const finance=(data.financial||[]).map(x=>'<div class="data-item"><b>'+esc(x.brand)+' · '+esc(x.currency)+' · net '+money(x.net,x.currency)+'</b><small>매출 '+money(x.revenue,x.currency)+' · 비용 '+money(x.costs,x.currency)+' · '+x.entries+'건</small></div>').join("");
    const evalStatus=evaluation.status==="holdout_available"?"시계열 홀드아웃 진단 가능":evaluation.status==="holdout_inconclusive"?"홀드아웃 결과 불충분":"검증 표본 수집 중";
    const within=evaluation.within_run_validation||{};
    const withinStatus=within.status==="holdout_available"?"동일 추천 세트 기준 홀드아웃 가능":"동일 추천 세트 표본 부족";
    const withinRho=within.holdout_median_score_views_spearman;
    const analyticsOutcomes=evaluation.analytics_outcome_validation||{};
    const analyticsLabels={engaged_view_share:"참여 조회 비율",average_view_percentage:"평균 시청 비율",average_view_duration_seconds:"평균 시청 시간",audience_watch_ratio_25:"25% 구간 유지율",audience_watch_ratio_50:"50% 구간 유지율",audience_watch_ratio_75:"75% 구간 유지율"};
    const analyticsSummary=Object.entries(analyticsOutcomes).map(([key,value])=>esc(analyticsLabels[key]||key)+': '+esc(value.status||'표본 부족')+' · 홀드아웃 '+Number(value.holdout_run_count||0)+'개 / 유효 노출 '+Number(value.eligible_run_count||0)+'개').join(' | ');
    const evaluationPanel='<h4>추천 알고리즘 홀드아웃 검증</h4><div class="data-item"><b>'+esc(evalStatus)+' · '+Number(evaluation.measured_outcome_count||0)+'개 조회속도 실측 / 선택 제작 '+Number(evaluation.selected_production_count||0)+'개</b><small>교차 노출 단순 참고 ρ '+(evaluation.holdout_score_views_spearman===null||evaluation.holdout_score_views_spearman===undefined?"—":Number(evaluation.holdout_score_views_spearman).toFixed(3))+' · 학습 '+Number(evaluation.pre_holdout_count||0)+'개 / 홀드아웃 '+Number(evaluation.holdout_count||0)+'개</small><small><b>'+esc(withinStatus)+'</b> · 유효 노출 '+Number(within.eligible_run_count||0)+'개 · 학습 '+Number(within.pre_holdout_run_count||0)+'개 / 홀드아웃 '+Number(within.holdout_run_count||0)+'개 · 동일 노출 중앙 Spearman ρ '+(withinRho===null||withinRho===undefined?"—":Number(withinRho).toFixed(3))+' · 순위 ρ '+(within.holdout_median_rank_views_spearman===null||within.holdout_median_rank_views_spearman===undefined?"—":Number(within.holdout_median_rank_views_spearman).toFixed(3))+' · 양의 연관 비율 '+(within.holdout_positive_score_association_share===null||within.holdout_positive_score_association_share===undefined?"—":Math.round(Number(within.holdout_positive_score_association_share)*100)+'%')+'</small><small>시청 품질 지표: '+(analyticsSummary||'Analytics 실측 표본 수집 중')+'</small><small>'+esc(within.reason||evaluation.reason||"")+'</small><small>'+esc(evaluation.pooled_metric_boundary||"")+'</small><small class="recommendation-caveat">'+esc(evaluation.warning||"")+' 점수 자동 조정은 비활성 상태입니다.</small></div>';
    const collection=analyticsCollection||{};
    const coverage=collection.coverage||{};
    const batch=collection.last_batch||{};
    const collectionLabels={not_started:"수집 이력 없음",running:"수집 중",succeeded:"정상 완료",partial:"일부 영상 실패",failed:"수집 실패"};
    const analyticsCollectionPanel='<h4>YouTube Analytics 자동 수집 상태</h4><div class="data-item"><b>'+esc(collectionLabels[collection.status]||collection.status||"상태 미확인")+' · 최근 배치 '+Number(batch.collected||0)+'/'+Number(batch.requested||0)+'개 수집</b><small>게시 영상 '+Number(coverage.published_videos||0)+'개 · Analytics 기록 '+Number(coverage.with_snapshot||0)+'개 · 미수집 '+Number(coverage.without_snapshot||0)+'개 · 오래된/미수집 '+Number(coverage.stale_or_missing||0)+'개</small><small>최근 시도 '+esc(collection.last_attempt_at||"없음")+' · 최근 정상 배치 '+esc(collection.last_success_at||"없음")+' · 마지막 보고서 '+esc(collection.latest_snapshot_at||"없음")+'</small><small>실패 '+Number(batch.failed||0)+'개'+(collection.last_error?' · '+esc(collection.last_error):"")+' · '+esc(collection.source||"YouTube Analytics API v2")+'</small></div>';
    $("insightList").innerHTML=analyticsCollectionPanel+evaluationPanel+'<h4>브랜드 성과</h4>'+(brands||'<div class="empty-state">업로드된 영상 데이터가 없습니다.</div>')+'<h4>지역별 성과</h4>'+(regions||'<div class="empty-state">지역별 데이터가 없습니다.</div>')+'<h4>비교 가능한 성과 코호트</h4>'+(cohorts||'<div class="empty-state">비교 조건을 만족하는 측정 표본이 아직 없습니다.</div>')+'<h4>YouTube 시청 유지율 비교 코호트</h4>'+(analyticsCohorts||'<div class="empty-state">동일 조건의 Analytics 비교 표본이 아직 없습니다.</div>')+'<h4>영상별 측정 상태</h4>'+(videos||'<div class="empty-state">영상 측정 데이터가 없습니다.</div>')+'<h4>실제 기록 금융 데이터 (통화별)</h4>'+(finance||'<div class="empty-state">기록된 금융 데이터가 없습니다.</div>')+'<div class="notice">'+(data.limitations||[]).map(esc).join(" · ")+'</div>';
  }

  async function loadPreflight(){
    const data=await api("/api/preflight");
    const labels={operator_auth:"운영자 인증",operator_rbac:"운영자 역할·권한 설정",script_generation:"AI 대본",voice_generation:"AI 음성",video_rendering:"영상 렌더링",artifact_staging:"렌더링 파일 스테이징",youtube_upload:"YouTube 업로드 OAuth",youtube_oauth:"YouTube OAuth 암호화 저장",youtube_data_api:"YouTube 데이터 API",tiktok_oauth:"TikTok Login Kit OAuth",tiktok_static_token:"TikTok 정적 토큰 대체 설정",media_directory:"미디어 저장소",backup_encryption:"백업 암호화 키",media_malware_scan:"ClamAV 미디어 악성코드 검사"};
    const checks=Object.entries(data.checks||{}).map(([key,value])=>{const missing=(value.missing||[]).join(", ");const optional=(value.optional_missing||[]).length?"선택 항목(미설정): "+value.optional_missing.join(", "):"";return '<div class="data-item"><b>'+esc(labels[key]||key)+' · <span class="'+(value.configured?"ready-text":"missing-text")+'">'+(value.configured?"필수 설정 확인":"필수 설정 누락")+'</span></b><small>'+esc([missing,optional].filter(Boolean).join(" · ")||(value.configured?"필수 설정값 존재":"설정 필요"))+'</small></div>';}).join("");
    const platforms=Object.entries(data.platforms||{}).map(([key,value])=>{const label=key==="youtube"?"YouTube Shorts":"TikTok";return '<div class="data-item"><b>'+label+' 제작·게시 준비 · <span class="'+(value.configuration_ready?"ready-text":"missing-text")+'">'+(value.configuration_ready?"설정 확인":"설정 미완료")+'</span></b><small>측정 API 설정: '+(value.metrics_configured?"확인":"미확인")+' · 실계정 연결·통신 검증: '+(value.live_connectivity_verified?"완료":"미실행")+(value.static_token_fallback?" · 정적 토큰 대체 방식":"")+(value.oauth_configured===false&&key==="tiktok"?" · OAuth 설정 필요":"")+'</small></div>';}).join("");
    $("preflightList").innerHTML=checks+platforms+'<div class="notice"><b>'+(data.capabilities.end_to_end_configured?"YouTube 설정 구성 완료":"외부 연동 설정이 더 필요합니다")+'</b><span>'+esc(data.note)+'</span></div>';
  }
  async function loadQueue(){
    const [q,w,control]=await Promise.all([
      api("/api/queue/stats"),api("/api/workers"),api("/api/queue/control")
    ]);
    const state=control.control||{};
    $("pauseQueue").disabled=!!state.paused;
    $("resumeQueue").disabled=!state.paused;
    const status=state.paused
      ? '<span class="missing-text">중지됨</span> · '+esc(state.pause_reason||"사유 없음")
      : '<span class="ready-text">정상 운영</span>';
    const events=(control.events||[]).slice(0,8).map(x=>'<div class="data-item"><b>'+esc(x.event_type)+' · '+esc(x.actor)+'</b><small>'+esc(x.created_at)+' · '+esc(x.reason)+'</small></div>').join("");
    $("queueDetails").innerHTML=
      '<div class="data-item"><b>생산 큐 제어 · '+status+'</b><small>중지 작업: '+esc(state.paused_job_id||"없음")+' · 갱신 '+esc(state.updated_at||"")+'</small></div>'+
      '<div class="data-item"><b>Queue status</b><small>'+esc(JSON.stringify(q))+'</small></div>'+
      (w.workers||[]).map(x=>'<div class="data-item"><b>'+esc(x.worker_id)+' · '+esc(x.status==="stale"?"응답 지연":x.status==="offline"?"오프라인":"온라인")+'</b><small>'+esc(x.hostname||"")+' · 마지막 응답 '+esc(x.last_seen_at||"")+' · 경과 '+esc(Number(x.heartbeat_age_seconds||0))+'초 / 기준 '+esc(Number(x.stale_after_seconds||0))+'초</small></div>').join("")+
      '<h4>운영 중지·재개 감사 기록</h4>'+(events||'<div class="empty-state">아직 제어 이력이 없습니다.</div>');
  }
  let integrityNextOffset = null;
  async function loadIntegrityReport(offset=0,append=false){
    const report=await api("/api/production/integrity-report?limit=50&offset="+encodeURIComponent(offset));
    const paused=!!report.worker_control?.paused,count=Number(report.unresolved||0);
    const scanned=Number(report.scanned||0);
    const shown=offset+scanned;
    const more=report.has_more?" · 다음 페이지 있음":"";
    $("integritySummary").innerHTML='<div class="integrity-status '+(count?"integrity-warning":"integrity-clear")+'"><b>'+count.toLocaleString()+'건 미해결</b><span>표시 '+shown.toLocaleString()+'건 / 전체 '+count.toLocaleString()+'건'+more+' · '+(paused?"작업 큐 중지":"작업 큐 정상")+'</span></div>';
    const labels={approval_or_upload_boundary:"승인·업로드 경계",ambiguous_external_outcome:"외부 실행 결과 불명확",terminal_state_mismatch:"종료 상태 불일치",review_handoff_mismatch:"검수 인계 불일치",unclassified_lifecycle_mismatch:"분류되지 않은 상태 불일치",queue_without_production_record:"제작 원장 누락",production_without_queue_record:"작업 큐 누락"};
    const items=Array.isArray(report.items)?report.items:[];
    const rendered=items.length?items.map(item=>{
      const history=Array.isArray(item.audit_history)?item.audit_history:[];
      const audit=history.map(event=>'<div class="integrity-audit"><b>'+esc(event.event_type)+' · '+esc(event.from_status||"—")+' → '+esc(event.to_status||"—")+'</b><small>'+esc(event.created_at||"")+(event.worker_id?' · worker '+esc(event.worker_id):"")+'</small></div>').join("");
      return '<article class="integrity-item"><div class="integrity-item-head"><b>'+esc(labels[item.classification]||item.classification||"상태 불일치")+'</b><code>'+esc(item.job_id)+'</code></div><div class="integrity-ledgers"><div><small>제작 원장</small><strong>'+esc(item.production_status)+'</strong><time>'+esc(item.production_updated_at||"")+'</time></div><div><small>작업 큐</small><strong>'+esc(item.queue_status)+'</strong><time>'+esc(item.queue_updated_at||"")+'</time></div></div><p>'+esc(item.reason||"원인 정보 없음")+'</p><p class="integrity-next"><b>권장 조치</b> '+esc(item.recommended_action||"운영자 확인 필요")+'</p>'+(item.error_code||item.error_message?'<small class="integrity-error">큐 오류: '+esc(item.error_code||"")+' '+esc(item.error_message||"")+'</small>':"")+(audit?'<details><summary>최근 감사 이력 '+history.length+'건</summary>'+audit+'</details>':'')+'<small class="integrity-boundary">진단 전용 · 자동 복구·재시도·승인·게시 없음</small></article>';
    }).join(""):'<div class="empty-state">'+(count?"현재 표시할 불일치 항목이 없습니다. 조회 한도를 확인하세요.":"제작 원장과 작업 큐의 상태 불일치가 발견되지 않았습니다.")+'</div>';
    $("integrityList").innerHTML=append?$("integrityList").innerHTML+rendered:rendered;
    integrityNextOffset=report.next_offset;
    $("integrityMore").hidden=!report.has_more;
  }
  async function refreshAll(){
    if(!token){setConnection(false,"인증 필요");return;}
    try{
      await Promise.all([loadMetrics(),loadFinance(),loadReviews(),loadApproved(),loadYouTubeConnection(),loadTikTokConnection(),loadTikTokMetrics(),loadTrends(),loadTrendRecommendations(),loadRecommendationEvaluation(),loadSchedules(),loadInsights(),loadOpportunities(),loadQueue(),loadIntegrityReport(),loadPreflight()]);
      toast("운영 데이터 갱신 완료");
    }catch(e){setConnection(false,"인증·API 확인 필요");toast(e.message);}
  }
  function requireToken(){if(!token){$("settingsDialog").showModal();return false;}return true;}
  function queueControlPayload(){
    const operator_id=$("queueOperator").value.trim();
    const note=$("queueControlNote").value.trim();
    if(!operator_id||!note){toast("운영자 ID와 조치 사유를 입력하세요.");return null;}
    return {operator_id,note};
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
    if(!confirm("외부 AI 공급자 기록, 생성 파일, 과금 상태를 확인하셨습니까? 확인 후 제작 큐를 재개합니다."))return;
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
  $("youtubeConnect").addEventListener("click",async()=>{
    if(!requireToken())return;
    try{
      const result=await api("/api/youtube/oauth/start");
      if(!result.authorization_url)throw new Error("Google authorization URL was not returned");
      window.location.assign(result.authorization_url);
    }catch(err){toast(err.message);}
  });
  $("loadYouTubeConnection").addEventListener("click",()=>loadYouTubeConnection().catch(e=>toast(e.message)));
  $("youtubeVerify").addEventListener("click",async()=>{
    if(!requireToken())return;
    const button=$("youtubeVerify");
    button.disabled=true;
    try{
      const result=await api("/api/youtube/oauth/verify",{method:"POST"});
      if(result.data_api_verified&&result.analytics_api_verified){
        toast("YouTube 실계정 연결 확인 완료 · "+(result.channel_title||result.channel_id));
      }else if(result.data_api_verified){
        toast("YouTube Data API 연결 확인 · Analytics 권한/접근은 미확인");
      }else{
        toast("YouTube 계정 검증 실패 · "+(result.error||"권한 또는 연결 설정 확인"));
      }
      await loadYouTubeConnection();
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("youtubeDisconnect").addEventListener("click",async()=>{
    if(!requireToken())return;
    if(!confirm("저장된 YouTube OAuth 연결을 해제하시겠습니까? 업로드와 Analytics 갱신이 중지됩니다."))return;
    try{
      await api("/api/youtube/oauth/disconnect",{method:"POST"});
      toast("YouTube OAuth 연결을 해제했습니다.");
      await loadYouTubeConnection();
    }catch(err){toast(err.message);}
  });
  $("tiktokConnect").addEventListener("click",async()=>{
    if(!requireToken())return;
    try{
      const result=await api("/api/tiktok/oauth/start");
      if(!result.authorization_url)throw new Error("TikTok authorization URL was not returned");
      window.location.assign(result.authorization_url);
    }catch(err){toast(err.message);}
  });
  $("loadTikTokMetrics").addEventListener("click",()=>loadTikTokMetrics().catch(e=>toast(e.message)));

  $("scheduleList").addEventListener("click",async e=>{
    const button=e.target.closest("button[data-schedule-outbox-retry]");
    if(!button)return;
    if(!requireToken())return;
    const outboxId=button.dataset.scheduleOutboxRetry;
    if(!confirm("격리된 예약 실행을 다시 대기열에 넣으시겠습니까? 해당 예약이 활성 상태여야 하며, 기존 실행 식별자는 유지됩니다."))return;
    button.disabled=true;
    try{
      await api("/api/schedules/outbox/"+encodeURIComponent(outboxId)+"/retry",{method:"POST"});
      toast("수동 재시도 요청 완료");
      await loadSchedules();
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("loadSchedules").addEventListener("click",()=>loadSchedules().catch(e=>toast(e.message)));
  $("loadIntegrity").addEventListener("click",()=>loadIntegrityReport().catch(e=>toast(e.message)));
  $("integrityMore").addEventListener("click",()=>{if(integrityNextOffset!==null)loadIntegrityReport(integrityNextOffset,true).catch(e=>toast(e.message));});
  $("loadInsights").addEventListener("click",()=>loadInsights().catch(e=>toast(e.message)));
  $("insightList").addEventListener("click",async e=>{
    const button=e.target.closest("button[data-youtube-analytics-refresh]");
    if(!button)return;
    if(!requireToken())return;
    const videoId=button.dataset.youtubeAnalyticsRefresh;
    button.disabled=true;
    try{
      const result=await api("/api/youtube/videos/"+encodeURIComponent(videoId)+"/refresh-analytics",{method:"POST"});
      toast("YouTube Analytics 갱신 완료 · 평균 시청 "+(result.metrics.average_view_duration_seconds===null?"—":Number(result.metrics.average_view_duration_seconds).toFixed(1)+"초")+" · 유지율 "+result.retention_status);
      await loadInsights();
    }catch(err){toast(err.message);}
    finally{button.disabled=false;}
  });
  $("loadPreflight").addEventListener("click",()=>loadPreflight().catch(e=>toast(e.message)));
  $("productionForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const result=await api("/api/production/jobs",{method:"POST",body:JSON.stringify({brand:$("brandSelect").value,region:$("regionSelect").value,language:$("languageSelect").value,topic:$("topicInput").value.trim(),platforms:[$("productionPlatform").value]})});msg("productionMessage","작업 등록 완료 · "+result.job.id);$("topicInput").value="";await refreshAll();}
    catch(err){msg("productionMessage",err.message,true);}
  });
  $("trendForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{const r=await api("/api/trends/collect",{method:"POST",body:JSON.stringify({region:$("trendRegion").value,query:$("trendQuery").value.trim(),limit:Number($("trendLimit").value),include_hacker_news:true})});msg("trendList","수집 완료 · "+(r.stored??r.count??"저장 결과 확인"));await Promise.all([loadTrends(),loadTrendRecommendations()]);}
    catch(err){toast(err.message);}
  });

  $("loadTrendRecommendations").addEventListener("click",()=>loadTrendRecommendations().catch(e=>toast(e.message)));
  $("loadRecommendationEvaluation").addEventListener("click",()=>loadRecommendationEvaluation().catch(e=>toast(e.message)));
  $("trendPlatform").addEventListener("change",()=>Promise.all([loadTrendRecommendations(),loadRecommendationEvaluation()]).catch(e=>toast(e.message)));

  $("trendRecommendations").addEventListener("click",async e=>{
    const button=e.target.closest("[data-recommend-draft]");
    if(!button)return;
    if(!requireToken())return;
    const selector=button.parentElement.querySelector("select[data-recommend-brand]");
    if(!selector)return;
    button.disabled=true;
    try{
      const result=await api("/api/trends/"+encodeURIComponent(button.dataset.recommendDraft)+"/draft-production",{
        method:"POST",body:JSON.stringify({brand:selector.value,language:button.dataset.recommendLanguage,platform:button.dataset.recommendPlatform||$("trendPlatform").value,recommendation_run_id:button.dataset.recommendRun||null})
      });
      toast("추천 후보 제작 기획 등록 완료 · "+result.job.id+(result.recommendation_attribution?.linked?" · 추천 실행 귀속 완료":" · 추천 실행 귀속 미확인"));
      await loadMetrics();
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
    const tiktokRefresh=e.target.closest("button[data-tiktok-refresh-id]");
    if(tiktokRefresh){
      if(!requireToken())return;
      const id=tiktokRefresh.dataset.tiktokRefreshId;
      try{
        await api("/api/tiktok/publications/"+encodeURIComponent(id)+"/refresh-status",{method:"POST"});
        toast("TikTok 게시 상태를 갱신했습니다.");await refreshAll();
      }catch(err){toast(err.message);}
      return;
    }
    const tiktokReconcile=e.target.closest("button[data-tiktok-reconcile-id]");
    if(tiktokReconcile){
      if(!requireToken())return;
      const id=tiktokReconcile.dataset.tiktokReconcileId;
      const outcome=prompt("TikTok 계정에서 확인한 결과를 입력하세요: published 또는 not_published");
      if(outcome===null)return;
      const normalized=outcome.trim().toLowerCase();
      if(!["published","not_published"].includes(normalized)){toast("published 또는 not_published만 입력할 수 있습니다.");return;}
      let videoId=null;
      if(normalized==="published"){
        videoId=prompt("TikTok에서 확인한 영상 ID를 입력하세요.");
        if(videoId===null||!videoId.trim())return;
      }else if(!confirm("TikTok 계정에서 해당 게시물이 생성되지 않았음을 직접 확인하셨습니까? 확인 후에만 재시도할 수 있습니다."))return;
      const note=prompt("TikTok 게시 결과를 확인한 근거를 입력하세요.");
      if(note===null||!note.trim())return;
      try{
        await api("/api/tiktok/publications/"+encodeURIComponent(id)+"/reconcile",{method:"POST",
          body:JSON.stringify({outcome:normalized,confirmed:true,video_id:videoId,note:note.trim(),operator_id:reviewer||"operator"})});
        toast("TikTok 게시 결과 대조가 기록되었습니다.");await refreshAll();
      }catch(err){toast(err.message);}
      return;
    }
    const tiktokPublish=e.target.closest("button[data-tiktok-publish-id]");
    if(tiktokPublish){
      if(!requireToken())return;
      const id=tiktokPublish.dataset.tiktokPublishId;
      try{
        const oauth=await api("/api/tiktok/oauth/status");
        if(!oauth.connected){
          const start=await api("/api/tiktok/oauth/start");
          if(!start.authorization_url)throw new Error("TikTok authorization URL was not returned");
          window.location.assign(start.authorization_url);return;
        }
        const creator=await api("/api/tiktok/creator-info");
        if(!(creator.privacy_level_options||[]).includes("SELF_ONLY"))
          throw new Error("현재 TikTok 계정에서 SELF_ONLY 비공개 게시 옵션을 사용할 수 없습니다.");
        $("tiktokConnectionStatus").textContent="연결됨 · "+esc(creator.creator_nickname||creator.creator_username||"TikTok 계정")+
          " · 최대 "+Number(creator.max_video_post_duration_sec||0)+"초 · 비공개 게시";
        const staged=await api("/api/production/jobs/"+encodeURIComponent(id)+"/stage-media",{method:"POST"});
        if(staged.review_required){
          toast("미디어 지문을 승인 기록에 반영했습니다. 콘텐츠를 다시 검수·승인한 뒤 게시하세요.");
          await refreshAll();return;
        }
        const title=prompt("TikTok 게시 문구 (최대 2,200자)","Shorts · "+id.slice(0,8));
        if(title===null||!title.trim())return;
        if(!confirm("이 승인된 영상을 TikTok에 전송하는 데 동의하십니까? 공개 범위는 SELF_ONLY(나만 보기)로 제한됩니다."))return;
        const brandContent=confirm("다른 브랜드/제3자와의 유료 파트너십 또는 협찬 콘텐츠입니까? 해당하면 확인을 누르세요.");
        const brandOwn=confirm("자신의 브랜드/사업을 홍보하는 콘텐츠입니까? 해당하면 확인을 누르세요.");
        if(brandContent&&brandOwn){
          toast("제3자 협찬과 자체 브랜드 홍보를 동시에 선택하지 마세요. 실제 관계에 맞게 한 항목만 선택하세요.");
          return;
        }
        await api("/api/tiktok/publish/"+encodeURIComponent(id),{method:"POST",body:JSON.stringify({
          media_path:staged.media_path,title:title.trim(),operator_id:reviewer||"operator",
          privacy_level:"SELF_ONLY",explicit_consent:true,
          brand_content_toggle:brandContent,brand_organic_toggle:brandOwn
        })});
        toast("TikTok 비공개 게시 요청이 접수되었습니다.");await refreshAll();
      }catch(err){$("upload-"+CSS.escape(id)).textContent=err.message;toast(err.message);}
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
    try{await api("/api/schedules",{method:"POST",body:JSON.stringify({name:$("scheduleName").value,interval_seconds:Number($("scheduleHours").value)*3600,brand:$("scheduleBrand").value,region:$("scheduleRegion").value,language:$("scheduleLanguage").value,topic:$("scheduleTopic").value,platform:$("schedulePlatform").value})});toast("예약 제작 등록 완료");await loadSchedules();}
    catch(err){toast(err.message);}
  });
  $("ledgerForm").addEventListener("submit",async e=>{
    e.preventDefault();if(!requireToken())return;
    try{await api("/api/finance/ledger",{method:"POST",body:JSON.stringify({brand:$("ledgerBrand").value,region:$("ledgerRegion").value,entry_type:$("ledgerType").value,amount:Number($("ledgerAmount").value),currency:$("ledgerCurrency").value,source_type:"operator_receipt",source_reference:$("ledgerReference").value,occurred_at:new Date($("ledgerDate").value+"T12:00:00Z").toISOString(),note:"Entered via NEXUS dashboard"})});msg("ledgerMessage","거래 장부 기록 완료");await Promise.all([loadMetrics(),loadFinance()]);}
    catch(err){msg("ledgerMessage",err.message,true);}
  });
  $("ledgerCurrency").addEventListener("change",()=>loadFinance().catch(e=>toast(e.message)));
  $("ledgerDate").value=new Date().toISOString().slice(0,10);
  const youtubeOAuthResult=new URLSearchParams(window.location.search).get("youtube_oauth");
  if(youtubeOAuthResult==="connected")toast("YouTube OAuth 승인 및 암호화 토큰 저장 완료 · 실계정 API 검증은 별도입니다.");
  else if(youtubeOAuthResult==="error"||youtubeOAuthResult==="denied")toast("YouTube OAuth 연결이 완료되지 않았습니다. 설정과 동의 권한을 확인하세요.");
  loadBrands().then(()=>{setConnection(false,"API 인증 필요");}).catch(e=>setConnection(false,"API 연결 실패: "+e.message));
})();