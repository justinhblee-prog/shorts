(() => {
  const $ = id => document.getElementById(id);
  const api = () => window.NexusStudioApi;
  const local = () => window.NexusLocalTimeline;
  const state = { audio:null, snapshotId:"", workspaceId:"", artifactId:"", rendering:false, outputUrl:"" };
  const say = (message,mode="info") => {
    const el=$("timelineStatus");if(el){el.textContent=message;el.dataset.state=mode;}
  };
  const pathFor = (workspace,suffix) => "/api/operator/workspaces/"+encodeURIComponent(workspace)+suffix;
  const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
  const secondsToMs = value => Math.max(0,Math.round(Number(value||0)*1000));
  const msToSeconds = value => Number(value||0)/1000;
  const currentWorkspace = () => api()?.getWorkspaceId() || "";
  const videoClips = () => (local()?.state.clips||[]).filter(clip=>clip.kind==="video");
  const titleClips = () => (local()?.state.clips||[]).filter(clip=>clip.kind==="title");
  function requireEditorContext(){
    if(!api()?.hasToken()){say("실제 렌더링을 위해 설정에서 백엔드 API 주소와 운영자 토큰을 연결하세요.","error");return false;}
    if(!currentWorkspace()){say("상단 워크스페이스를 선택하거나 새 작업공간을 생성하세요.","error");return false;}
    return true;
  }
  async function createWorkspace(){
    if(!api()?.hasToken()){say("워크스페이스 생성 전에 운영자 토큰을 연결하세요.","error");return;}
    const name=$("timelineWorkspaceName").value.trim();
    if(!name){say("새 작업공간 이름을 입력하세요.","error");return;}
    const button=$("timelineCreateWorkspace");button.disabled=true;
    try{
      const result=await api().request("/api/operator/workspaces",{method:"POST",body:JSON.stringify({name})});
      const id=result.id||result.workspace_id;
      if(!id)throw new Error("서버가 작업공간 ID를 반환하지 않았습니다.");
      await api().selectWorkspace(id);
      $("timelineWorkspaceName").value="";
      say("작업공간 생성 및 선택 완료 · "+id,"success");
    }catch(error){say("작업공간 생성 실패 · "+error.message,"error");}
    finally{button.disabled=false;}
  }
  async function uploadAsset(file,workspaceId,existingAssetId="",onUploaded=()=>{}){
    let asset;
    if(existingAssetId){
      const stored=await api().request("/api/workspaces/"+encodeURIComponent(workspaceId)+"/assets/"+encodeURIComponent(existingAssetId));
      asset=stored.asset||stored;
      asset.asset_id=asset.asset_id||asset.id||existingAssetId;
    }else{
      const url=pathFor(workspaceId,"/assets")+"?filename="+encodeURIComponent(file.name);
      asset=await api().request(url,{method:"POST",body:file,headers:{"Content-Type":file.type||"application/octet-stream"}});
      asset.asset_id=asset.asset_id||asset.id;
      if(!asset.asset_id)throw new Error(file.name+" · 업로드 응답에 asset ID가 없습니다.");
      onUploaded(asset);
    }
    if(asset.scan_status!=="clean"){
      const rescan=await api().request(pathFor(workspaceId,"/assets/"+encodeURIComponent(asset.asset_id)+"/scan"),{method:"POST"});
      asset={...asset,...rescan};
    }
    const renderable=asset.renderable===true||(asset.renderable==null&&asset.scan_status==="clean"&&!!asset.media_metadata);
    if(asset.scan_status!=="clean"||!renderable){
      throw new Error(file.name+" · 서버 보안/미디어 검사가 통과되지 않았습니다 ("+(asset.scanner_status||asset.scan_status||"unknown")+")");
    }
    return asset;
  }
  async function ensureVideoAssets(workspaceId){
    const clips=videoClips();
    if(!clips.length)throw new Error("먼저 타임라인에 영상 클립을 추가하세요.");
    for(const clip of clips){
      if(!clip.file)throw new Error(clip.name+" · 원본 파일이 브라우저 메모리에 없습니다. 파일을 다시 불러오세요.");
      say("비공개 미디어 업로드 및 서버 검사 중 · "+clip.name);
      const existing=clip.uploadedWorkspaceId===workspaceId?clip.assetId:"";
      const asset=await uploadAsset(clip.file,workspaceId,existing,item=>{clip.assetId=item.asset_id;clip.uploadedWorkspaceId=workspaceId;});
      clip.assetId=asset.asset_id;clip.uploadedWorkspaceId=workspaceId;
      clip.serverDurationMs=Number(asset.media_metadata?.duration_ms||asset.duration_ms||0);
      if(!clip.serverDurationMs)throw new Error(clip.name+" · 서버가 영상 길이를 확인하지 못했습니다.");
      if(msToSeconds(clip.serverDurationMs)<clip.inPoint+0.1)throw new Error(clip.name+" · 편집 시작점이 서버에서 확인한 원본 길이를 초과합니다.");
      clip.outPoint=Math.min(clip.outPoint,msToSeconds(clip.serverDurationMs));
      clip.duration=msToSeconds(clip.serverDurationMs);
    }
    return clips;
  }
  async function ensureAudioAsset(workspaceId){
    if(!state.audio)return null;
    if(!state.audio.file)throw new Error("오디오 원본 파일을 다시 선택하세요.");
    say("오디오 업로드 및 서버 검사 중 · "+state.audio.file.name);
    const existing=state.audio.uploadedWorkspaceId===workspaceId?state.audio.assetId:"";
    const asset=await uploadAsset(state.audio.file,workspaceId,existing,item=>{state.audio.assetId=item.asset_id;state.audio.uploadedWorkspaceId=workspaceId;});
    state.audio.assetId=asset.asset_id;state.audio.uploadedWorkspaceId=workspaceId;
    state.audio.serverDurationMs=Number(asset.media_metadata?.duration_ms||asset.duration_ms||0);
    if(!state.audio.serverDurationMs)throw new Error("서버가 오디오 길이를 확인하지 못했습니다.");
    return state.audio;
  }
  async function buildEdl(workspaceId){
    const localState=local()?.state;
    if(!localState||localState.clips.length>20)throw new Error("EDL v1은 영상과 타이틀을 합쳐 최대 20개 클립을 지원합니다.");
    const clips=await ensureVideoAssets(workspaceId);
    const audio=await ensureAudioAsset(workspaceId);
    let cursor=0;
    const edlClips=[];
    for(const clip of clips){
      const sourceIn=secondsToMs(clip.inPoint);
      const sourceOut=Math.min(secondsToMs(clip.outPoint),clip.serverDurationMs||secondsToMs(clip.duration));
      if(sourceOut<=sourceIn)throw new Error(clip.name+" · 유효하지 않은 소스 구간입니다.");
      const duration=sourceOut-sourceIn;
      edlClips.push({id:clip.id,type:"video",start_ms:cursor,end_ms:cursor+duration,asset_id:clip.assetId,source_in_ms:sourceIn,source_out_ms:sourceOut});
      cursor+=duration;
    }
    if(cursor<=0)throw new Error("렌더링할 영상 구간이 없습니다.");
    for(const [index,clip] of titleClips().entries()){
      const start=Math.min(secondsToMs(clip.inPoint),Math.max(0,cursor-100));
      const end=Math.min(secondsToMs(clip.outPoint),cursor);
      if(end<=start)throw new Error("타이틀 클립의 시작·종료 시간을 확인하세요.");
      edlClips.push({id:clip.id,type:"title",start_ms:start,end_ms:end,text:clip.text});
    }
    const audioTracks=[];
    if(audio){
      const sourceOut=Math.min(audio.serverDurationMs,cursor);
      const fadeIn=Math.min(secondsToMs($("timelineAudioFadeIn").value),sourceOut);
      const fadeOut=Math.min(secondsToMs($("timelineAudioFadeOut").value),Math.max(0,sourceOut-fadeIn));
      audioTracks.push({id:"audio_bed_1",asset_id:audio.assetId,start_ms:0,source_in_ms:0,source_out_ms:sourceOut,gain:Math.max(0,Math.min(4,Number($("timelineAudioGain").value||1))),fade_in_ms:fadeIn,fade_out_ms:fadeOut});
    }
    return {schema:"nexus-edit-decision-list",version:1,timebase:"milliseconds",clips:edlClips,audio_tracks:audioTracks};
  }
  async function fetchArtifact(workspaceId,snapshotId){
    const listing=await api().request(pathFor(workspaceId,"/render-artifacts?limit=100"));
    const artifact=(listing.items||[]).find(item=>item.snapshot_id===snapshotId);
    if(!artifact)throw new Error("렌더 완료됐지만 검수 대기 산출물을 찾지 못했습니다.");
    state.artifactId=artifact.artifact_id;
    const blob=await api().requestBlob(pathFor(workspaceId,"/render-artifacts/"+encodeURIComponent(artifact.artifact_id)+"/download"));
    const video=$("timelineServerPreview");
    if(state.outputUrl)URL.revokeObjectURL(state.outputUrl);
    state.outputUrl=URL.createObjectURL(blob);video.src=state.outputUrl;video.hidden=false;
    $("timelineRenderReview").hidden=false;
    $("timelineCheckRender").disabled=false;
    say("렌더 완료 · "+(Number(artifact.duration_ms||0)/1000).toFixed(1)+"초 · "+Number(artifact.byte_size||0).toLocaleString()+" bytes · 사람 검수 대기","success");
  }
  async function checkRenderStatus(){
    const workspaceId=state.workspaceId||currentWorkspace();
    if(!workspaceId||!state.snapshotId){say("조회할 서버 렌더 작업이 없습니다.","error");return null;}
    const current=await api().request(pathFor(workspaceId,"/renders/"+encodeURIComponent(state.snapshotId)));
    say("서버 렌더 상태 · "+current.status+" · 작업 "+current.render_job_id+" · 시도 "+current.attempt+"/"+current.max_attempts);
    if(current.status==="review_pending")await fetchArtifact(workspaceId,state.snapshotId);
    else if(current.status==="failed"||current.status==="cancelled")say("서버 렌더가 "+current.status+" 상태입니다. 로그와 입력 미디어를 확인하세요.","error");
    return current;
  }
  async function submitRender(){
    if(state.rendering||!requireEditorContext())return;
    const workspaceId=currentWorkspace();
    state.rendering=true;state.workspaceId=workspaceId;
    $("timelineSubmitRender").disabled=true;$("timelineCheckRender").disabled=true;
    $("timelineRenderReview").hidden=true;
    try{
      say("원본 미디어를 비공개 워크스페이스에 등록하고 검사합니다.");
      const edl=await buildEdl(workspaceId);
      say("서버 측 EDL v1 검증 중 · 임의 경로/URL은 허용되지 않습니다.");
      const validation=await api().request("/api/timeline/edl/validate",{method:"POST",body:JSON.stringify(edl),headers:{"X-Nexus-Workspace-Id":workspaceId}});
      if(!validation.valid||!validation.edl)throw new Error("서버 EDL 검증이 완료되지 않았습니다.");
      const idempotency="nexus-edl-"+Date.now()+"-"+Math.random().toString(36).slice(2,10);
      const submitted=await api().request(pathFor(workspaceId,"/renders"),{method:"POST",body:JSON.stringify({edl:validation.edl,idempotency_key:idempotency})});
      state.snapshotId=submitted.snapshot_id;state.artifactId="";
      $("timelineCheckRender").disabled=false;
      say("렌더 작업 접수 · "+submitted.render_job_id+" · 불변 EDL 스냅샷 "+submitted.snapshot_id,"success");
      const deadline=Date.now()+900000;
      let status=submitted.status||"queued";
      while(Date.now()<deadline&&status!=="review_pending"&&status!=="failed"&&status!=="cancelled"){
        await sleep(3000);
        const current=await api().request(pathFor(workspaceId,"/renders/"+encodeURIComponent(state.snapshotId)));
        status=current.status;
        if(status==="review_pending"){await fetchArtifact(workspaceId,state.snapshotId);break;}
        if(status==="failed"||status==="cancelled")throw new Error("렌더 작업이 "+status+" 상태로 종료되었습니다.");
        say("렌더 작업 "+status+" · "+current.render_job_id+" · 시도 "+current.attempt+"/"+current.max_attempts);
      }
      if(status!=="review_pending")say("렌더 대기 시간이 초과되었습니다. '렌더 상태 확인'으로 작업을 계속 조회할 수 있습니다.","error");
    }catch(error){say("서버 렌더 제출 실패 · "+error.message,"error");}
    finally{state.rendering=false;$("timelineSubmitRender").disabled=false;}
  }
  async function decideRender(decision){
    if(!state.snapshotId||!state.workspaceId||!state.artifactId)return;
    const buttons=[$("timelineApproveRender"),$("timelineRevisionRender"),$("timelineRejectRender")];
    buttons.forEach(button=>button.disabled=true);
    try{
      const comment=$("timelineDecisionComment").value.trim();
      await api().request(pathFor(state.workspaceId,"/renders/"+encodeURIComponent(state.snapshotId)+"/decision"),{method:"POST",body:JSON.stringify({decision,comment})});
      $("timelineRenderReview").hidden=true;
      say(decision==="approved"?"렌더 산출물의 사람 검수 승인 기록 완료 · 게시/업로드는 실행하지 않았습니다.":decision==="rejected"?"렌더 산출물 반려 기록 완료 · 게시/업로드는 실행하지 않았습니다.":"수정 요청 기록 완료 · 게시/업로드는 실행하지 않았습니다.","success");
    }catch(error){say("검수 결정 실패 · "+error.message,"error");}
    finally{buttons.forEach(button=>button.disabled=false);}
  }
  async function loadAudio(file){
    const url=URL.createObjectURL(file),probe=new Audio();
    probe.preload="metadata";probe.src=url;
    $("timelineAudioStatus").textContent="오디오 길이 확인 중 · "+file.name;
    probe.addEventListener("loadedmetadata",()=>{
      if(state.audio?.url)URL.revokeObjectURL(state.audio.url);
      state.audio={file,url,duration:probe.duration,assetId:"",uploadedWorkspaceId:"",serverDurationMs:0};
      $("timelineAudioStatus").textContent=file.name+" · "+probe.duration.toFixed(1)+"초 · 서버 검사 전";
    },{once:true});
    probe.addEventListener("error",()=>{
      URL.revokeObjectURL(url);state.audio=null;$("timelineAudioStatus").textContent="오디오 메타데이터를 읽을 수 없습니다.";
    },{once:true});
  }
  function workspaceChanged(){
    const next=currentWorkspace();
    if(next!==state.workspaceId){
      state.workspaceId=next;
      state.snapshotId="";state.artifactId="";
      videoClips().forEach(clip=>{clip.assetId="";clip.uploadedWorkspaceId="";clip.serverDurationMs=0;});
      if(state.audio){state.audio.assetId="";state.audio.uploadedWorkspaceId="";state.audio.serverDurationMs=0;}
      $("timelineRenderReview").hidden=true;$("timelineCheckRender").disabled=true;
    }
  }
  function bind(){
    $("timelineCreateWorkspace").addEventListener("click",createWorkspace);
    $("timelineAudioInput").addEventListener("change",event=>{
      const file=event.target.files?.[0];if(file)loadAudio(file);event.target.value="";
    });
    $("timelineCheckRender").addEventListener("click",async()=>{
      if(!requireEditorContext())return;
      try{await checkRenderStatus();}catch(error){say("렌더 상태 조회 실패 · "+error.message,"error");}
    });
    $("timelineSubmitRender").addEventListener("click",submitRender);
    $("timelineApproveRender").addEventListener("click",()=>decideRender("approved"));
    $("timelineRevisionRender").addEventListener("click",()=>decideRender("revision_requested"));
    $("timelineRejectRender").addEventListener("click",()=>decideRender("rejected"));
    window.addEventListener("nexus:workspace-changed",workspaceChanged);
    window.addEventListener("nexus:auth-changed",()=>{if(!api()?.hasToken())say("API 인증이 초기화되었습니다. 렌더링을 계속하려면 다시 연결하세요.");});
    workspaceChanged();
  }
  if($("timelineEditor")){
    bind();
    window.addEventListener("beforeunload",()=>{if(state.audio?.url)URL.revokeObjectURL(state.audio.url);if(state.outputUrl)URL.revokeObjectURL(state.outputUrl);});
    if(!api()?.hasToken())say("편집 미리보기는 로컬에서 가능하며, 서버 렌더링에는 API 주소·토큰·활성 워크스페이스가 필요합니다.");
  }
})();
