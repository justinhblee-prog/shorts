(() => {
  const $ = id => document.getElementById(id);
  const api = () => window.NexusStudioApi;
  const local = () => window.NexusLocalTimeline;
  const state = { audios:[], snapshotId:"", workspaceId:"", artifactId:"", rendering:false, outputUrl:"", zoom:1 };
  const say = (message,mode="info") => {
    const el=$("timelineStatus");if(el){el.textContent=message;el.dataset.state=mode;}
  };
  function clearPrivatePreview(){
    const video=$("timelineServerPreview");
    if(video){video.pause();video.removeAttribute("src");video.load();video.hidden=true;video.style.display="none";}
    if(state.outputUrl){URL.revokeObjectURL(state.outputUrl);state.outputUrl="";}
    $("timelineRenderReview").hidden=true;
    $("timelineCheckRender").disabled=true;
    state.snapshotId="";state.artifactId="";
  }
  const pathFor = (workspace,suffix) => "/api/operator/workspaces/"+encodeURIComponent(workspace)+suffix;
  const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
  const secondsToMs = value => Math.max(0,Math.round(Number(value||0)*1000));
  const msToSeconds = value => Number(value||0)/1000;
  const currentWorkspace = () => api()?.getWorkspaceId() || "";
  const videoClips = () => (local()?.state.clips||[]).filter(clip=>clip.kind==="video");
  const titleClips = () => (local()?.state.clips||[]).filter(clip=>clip.kind==="title");
  const formatTime = value => Math.max(0,Number(value||0)).toFixed(1)+"s";
  const formatBytes = value => {
    const bytes=Number(value||0);if(bytes<1024)return bytes+" B";
    if(bytes<1024*1024)return (bytes/1024).toFixed(1)+" KB";
    if(bytes<1024*1024*1024)return (bytes/1024/1024).toFixed(1)+" MB";
    return (bytes/1024/1024/1024).toFixed(2)+" GB";
  };
  const transitionSettings = () => ({
    type:$("timelineTransitionType")?.value||"none",
    durationMs:Math.max(100,Math.min(5000,Math.round(Number($("timelineTransitionDuration")?.value)||500)))
  });
  function renderMediaShelf(){
    const shelf=$("timelineMediaShelf");if(!shelf)return;
    const clips=local()?.state.clips||[];
    const query=($("timelineMediaFilter")?.value||"").trim().toLocaleLowerCase();
    const visible=clips.filter(clip=>(clip.name+" "+clip.kind).toLocaleLowerCase().includes(query));
    $("timelineMediaShelfCount").textContent=visible.length+" / "+clips.length+" ITEMS";
    shelf.replaceChildren();
    if(!visible.length){
      const empty=document.createElement("div");empty.className="empty-state";
      empty.textContent=clips.length?"검색 결과가 없습니다.":"동영상을 추가하면 썸네일이 여기에 표시됩니다.";
      shelf.append(empty);
    }
    for(const clip of visible){
      const selected=local()?.state.selected===clip.id;
      const card=document.createElement("button");card.type="button";
      card.className="timeline-media-card"+(selected?" is-selected":"");
      card.setAttribute("aria-pressed",String(Boolean(selected)));
      card.setAttribute("aria-label",clip.name+" 미디어 선택");
      const thumb=document.createElement("span");thumb.className="timeline-media-thumb";
      if(clip.kind==="video"&&clip.url){
        const video=document.createElement("video");video.src=clip.url;video.muted=true;video.playsInline=true;video.preload="metadata";
        video.setAttribute("aria-hidden","true");
        video.addEventListener("loadedmetadata",()=>{
          const mediaDuration=Number.isFinite(video.duration)?video.duration:0;
          const target=Math.min(Math.max(0,clip.inPoint+0.12),Math.max(0,mediaDuration-0.08));
          if(Number.isFinite(target))try{video.currentTime=target;}catch{}
        },{once:true});
        video.addEventListener("seeked",()=>video.pause(),{once:true});
        video.addEventListener("error",()=>thumb.classList.add("is-unavailable"),{once:true});
        thumb.append(video);
        const play=document.createElement("span");play.className="timeline-thumb-play";play.textContent="▶";thumb.append(play);
      }else{
        thumb.classList.add("is-title");
        const glyph=document.createElement("b");glyph.textContent="Aa";thumb.append(glyph);
        const snippet=document.createElement("small");snippet.textContent=clip.text||clip.name;thumb.append(snippet);
      }
      const body=document.createElement("span");body.className="timeline-media-card-body";
      const name=document.createElement("b");name.className="timeline-media-name";name.textContent=clip.name;
      const meta=document.createElement("small");meta.textContent=clip.kind==="video"?formatTime(clip.outPoint-clip.inPoint)+" · "+formatBytes(clip.sizeBytes):"TITLE OVERLAY · "+formatTime(clip.outPoint-clip.inPoint);
      const status=document.createElement("span");status.className="timeline-media-status";
      if(clip.kind==="title"){status.textContent="타이틀 오버레이";status.classList.add("is-title");}
      else if(clip.uploadedWorkspaceId===currentWorkspace()&&clip.assetId&&clip.serverDurationMs){status.textContent="서버 검사 완료";status.classList.add("is-verified");}
      else if(clip.assetId){status.textContent="서버 검사 대기";status.classList.add("is-pending");}
      else{status.textContent="로컬 원본";status.classList.add("is-local");}
      body.append(name,meta,status);card.append(thumb,body);
      card.addEventListener("click",()=>{local()?.selectClip?.(clip.id);});
      shelf.append(card);
    }
    const selected=local()?.state.clips.find(clip=>clip.id===local()?.state.selected);
    const details=$("timelineSelectedMeta");
    if(details){
      details.replaceChildren();
      if(!selected){
        details.textContent="미디어를 선택하면 상세 정보가 표시됩니다.";
      }else{
        const rows=[
          ["유형",selected.kind==="video"?"VIDEO SOURCE":"TITLE OVERLAY"],
          ["원본 길이",selected.kind==="video"?formatTime(selected.duration):"—"],
          ["편집 구간",formatTime(selected.inPoint)+" — "+formatTime(selected.outPoint)],
          ["파일 크기",selected.kind==="video"?formatBytes(selected.sizeBytes):"—"],
          ["서버 상태",selected.kind==="title"?"렌더 시 영상에 합성":(selected.serverDurationMs?"검사 완료":selected.assetId?"검사 대기":"업로드 전")]
        ];
        rows.forEach(([label,value])=>{
          const row=document.createElement("div");row.className="timeline-meta-row";
          const key=document.createElement("span");key.textContent=label;
          const val=document.createElement("b");val.textContent=value;
          row.append(key,val);details.append(row);
        });
      }
    }
  }
  function applyTimelineZoom(value){
    state.zoom=Math.min(4,Math.max(1,Math.round(Number(value)*4)/4));
    const root=$("timelineVisualTrack");if(root)root.style.minWidth=Math.round(620*state.zoom)+"px";
    const slider=$("timelineZoomLevel");if(slider)slider.value=String(state.zoom);
    const label=$("timelineZoomValue");if(label)label.textContent=Math.round(state.zoom*100)+"%";
  }
  function scrollTimeline(direction){
    const panel=document.querySelector(".timeline-visual-track-panel");if(!panel)return;
    panel.scrollBy({left:direction*Math.max(180,Math.round(panel.clientWidth*.75)),behavior:"smooth"});
  }
  function renderVisualTrack(){
    const root=$("timelineVisualTrack");if(!root)return;
    root.style.minWidth=Math.round(620*state.zoom)+"px";
    const clips=local()?.state.clips||[];
    const videos=clips.filter(clip=>clip.kind==="video");
    const titles=clips.filter(clip=>clip.kind==="title");
    const transition=transitionSettings();
    const rawVideoDuration=videos.reduce((sum,clip)=>sum+Math.max(0,clip.outPoint-clip.inPoint),0);
    const joins=Math.max(0,videos.length-1);
    const videoDuration=Math.max(0,rawVideoDuration+(transition.type==="black-gap"?joins*transition.durationMs/1000:0)-(transition.type==="crossfade"?joins*transition.durationMs/1000:0));
    const requestedDuration=Number($("timelineProjectDuration")?.value||0);
    const duration=Math.max(videoDuration,Number.isFinite(requestedDuration)&&requestedDuration>0?requestedDuration:0);
    $("timelineVisualDuration").textContent=formatTime(duration);
    root.replaceChildren();
    if(!videos.length||duration<=0){
      const empty=document.createElement("div");empty.className="empty-state";empty.textContent="영상 클립을 추가하면 시간축이 생성됩니다.";root.append(empty);return;
    }
    const ruler=document.createElement("div");ruler.className="timeline-ruler";
    const step=duration>90?15:duration>45?10:5;
    const ticks=[];for(let t=0;t<duration;t+=step)ticks.push(t);if(!ticks.length||ticks[ticks.length-1]!==duration)ticks.push(duration);
    ticks.forEach(t=>{
      const tick=document.createElement("span");tick.className="timeline-ruler-tick";tick.style.left=(t/duration*100)+"%";tick.textContent=Math.round(t)+"s";ruler.append(tick);
    });
    root.append(ruler);
    const addLane=(label,className,items,makeSegment)=>{
      const row=document.createElement("div");row.className="timeline-visual-lane "+className;
      const title=document.createElement("b");title.className="timeline-lane-label";title.textContent=label;
      const track=document.createElement("div");track.className="timeline-lane-track";
      if(items.length)items.forEach(item=>track.append(makeSegment(item,track)));
      else{const empty=document.createElement("span");empty.className="timeline-lane-empty";empty.textContent=label==="AUDIO"?"오디오 트랙 없음":"클립 없음";track.append(empty);}
      row.append(title,track);root.append(row);
    };
    let cursor=0,previousVideo=null;
    addLane("VIDEO","is-video",videos,(clip,track)=>{
      const length=Math.max(0,clip.outPoint-clip.inPoint);
      const overlap=previousVideo&&transition.type==="crossfade"?transition.durationMs/1000:0;
      const blackGap=previousVideo&&transition.type==="black-gap"?transition.durationMs/1000:0;
      const start=Math.max(0,cursor-overlap+blackGap);
      if(overlap>0||blackGap>0){
        const marker=document.createElement("span");marker.className="timeline-transition-marker"+(blackGap>0?" is-black-gap":"");
        marker.style.left=((blackGap>0?cursor:start)/duration*100)+"%";marker.style.width=((overlap||blackGap)/duration*100)+"%";
        marker.textContent=blackGap>0?"BLACK":"DISSOLVE";
        marker.title=(blackGap>0?"검은 화면":"크로스페이드")+" · "+formatTime(overlap||blackGap);
        marker.setAttribute("aria-label",marker.title);track.append(marker);
      }
      const segment=document.createElement("button");
      segment.type="button";segment.className="timeline-segment is-video"+(local()?.state.selected===clip.id?" is-selected":"");
      segment.style.left=(start/duration*100)+"%";segment.style.width=(length/duration*100)+"%";segment.textContent=clip.name;segment.title=clip.name+" · "+formatTime(length);
      segment.addEventListener("click",()=>local()?.selectClip?.(clip.id));cursor=start+length;previousVideo=clip;return segment;
    });
    addLane("TITLE","is-title",titles,clip=>{
      const start=Math.min(clip.inPoint,duration),end=Math.min(clip.outPoint,duration),segment=document.createElement("button");
      segment.type="button";segment.className="timeline-segment is-title"+(local()?.state.selected===clip.id?" is-selected":"");
      segment.style.left=(start/duration*100)+"%";segment.style.width=(Math.max(0,end-start)/duration*100)+"%";segment.textContent=clip.text||clip.name;segment.title=clip.text||clip.name;
      segment.addEventListener("click",()=>local()?.selectClip?.(clip.id));return segment;
    });
    const audioItems=state.audios.map(track=>{
      const start=Math.max(0,track.startMs/1000),sourceIn=Math.max(0,track.sourceInMs/1000);
      const sourceOut=Math.min(track.serverDurationMs?msToSeconds(track.serverDurationMs):track.duration,track.sourceOutMs/1000);
      const length=Math.max(0,Math.min(sourceOut-sourceIn,duration-start));
      return {...track,timelineStart:start,timelineDuration:length};
    }).filter(track=>track.timelineDuration>0&&track.timelineStart<duration);
    addLane("AUDIO","is-audio",audioItems,item=>{
      const segment=document.createElement("span");segment.className="timeline-segment is-audio";
      segment.style.left=(item.timelineStart/duration*100)+"%";segment.style.width=(item.timelineDuration/duration*100)+"%";
      segment.textContent=item.name;segment.title=item.name+" · "+formatTime(item.timelineStart)+" 시작 · "+formatTime(item.timelineDuration);return segment;
    });
  }
  function renderTimelineViews(){renderMediaShelf();renderVisualTrack();}
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
    if(asset.scan_status==="pending"){
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
    local()?.render();
    return clips;
  }
  async function ensureAudioAssets(workspaceId){
    if(state.audios.length>8)throw new Error("EDL v1은 최대 8개 오디오 트랙을 지원합니다.");
    for(const track of state.audios){
      if(!track.file)throw new Error(track.name+" · 오디오 원본 파일을 다시 선택하세요.");
      say("오디오 업로드 및 서버 검사 중 · "+track.name);
      const existing=track.uploadedWorkspaceId===workspaceId?track.assetId:"";
      const asset=await uploadAsset(track.file,workspaceId,existing,item=>{track.assetId=item.asset_id;track.uploadedWorkspaceId=workspaceId;});
      track.assetId=asset.asset_id;track.uploadedWorkspaceId=workspaceId;
      track.serverDurationMs=Number(asset.media_metadata?.duration_ms||asset.duration_ms||0);
      if(!track.serverDurationMs)throw new Error(track.name+" · 서버가 오디오 길이를 확인하지 못했습니다.");
      if(track.sourceInMs>=track.serverDurationMs)throw new Error(track.name+" · 시작점이 원본 길이를 초과합니다.");
      track.sourceOutMs=Math.min(Number.isFinite(Number(track.sourceOutMs))?Number(track.sourceOutMs):track.serverDurationMs,track.serverDurationMs);
    }
    renderTimelineViews();return state.audios;
  }
  async function buildEdl(workspaceId){
    const localState=local()?.state;
    if(!localState||localState.clips.length>20)throw new Error("EDL v1은 영상과 타이틀을 합쳐 최대 20개 클립을 지원합니다.");
    const clips=await ensureVideoAssets(workspaceId);
    const audioTracksInput=await ensureAudioAssets(workspaceId);
    const transition=transitionSettings(),transitions=[],gaps=[];
    let cursor=0,previousClip=null,previousDuration=0;
    const edlClips=[];
    for(const clip of clips){
      const sourceIn=secondsToMs(clip.inPoint);
      const sourceOut=Math.min(secondsToMs(clip.outPoint),clip.serverDurationMs||secondsToMs(clip.duration));
      if(sourceOut<=sourceIn)throw new Error(clip.name+" · 유효하지 않은 소스 구간입니다.");
      const duration=sourceOut-sourceIn;
      const overlap=previousClip&&transition.type==="crossfade"?transition.durationMs:0;
      const gap=previousClip&&transition.type==="black-gap"?transition.durationMs:0;
      if(overlap>0&&(overlap>=duration||overlap>=previousDuration))throw new Error("크로스페이드 길이는 연결된 두 영상 클립 각각의 길이보다 짧아야 합니다.");
      const start=Math.max(0,cursor-overlap+gap);
      edlClips.push({id:clip.id,type:"video",start_ms:start,end_ms:start+duration,asset_id:clip.assetId,source_in_ms:sourceIn,source_out_ms:sourceOut});
      if(overlap>0)transitions.push({from_clip_id:previousClip.id,to_clip_id:clip.id,type:"crossfade",duration_ms:overlap});
      if(gap>0)gaps.push({after_clip_id:previousClip.id,before_clip_id:clip.id,duration_ms:gap});
      cursor=start+duration;previousClip=clip;previousDuration=duration;
    }
    if(cursor<=0)throw new Error("렌더링할 영상 구간이 없습니다.");
    const projectDurationRaw=$("timelineProjectDuration").value.trim();
    let projectDurationMs=cursor;
    if(projectDurationRaw){
      const requestedSeconds=Number(projectDurationRaw);
      if(!Number.isFinite(requestedSeconds)||requestedSeconds<=0||requestedSeconds>3600)throw new Error("프로젝트 길이는 0초 초과, 3600초 이하로 입력하세요.");
      projectDurationMs=secondsToMs(requestedSeconds);
      if(projectDurationMs<cursor)throw new Error("프로젝트 길이는 전체 영상 클립 길이보다 짧을 수 없습니다.");
    }
    for(const [index,clip] of titleClips().entries()){
      const start=Math.min(secondsToMs(clip.inPoint),Math.max(0,projectDurationMs-100));
      const end=Math.min(secondsToMs(clip.outPoint),projectDurationMs);
      if(end<=start)throw new Error("타이틀 클립의 시작·종료 시간을 확인하세요.");
      edlClips.push({id:clip.id,type:"title",start_ms:start,end_ms:end,text:clip.text});
    }
    const audioTracks=audioTracksInput.map((track,index)=>{
      const startMs=Math.max(0,Math.round(Number(track.startMs)||0));
      if(startMs>=projectDurationMs)throw new Error(track.name+" · 시작 위치가 프로젝트 길이보다 늦습니다.");
      const sourceIn=Math.max(0,Math.round(Number(track.sourceInMs)||0)),requestedSourceOut=Number(track.sourceOutMs);
      const sourceOut=Math.min(track.serverDurationMs,Number.isFinite(requestedSourceOut)?Math.round(requestedSourceOut):track.serverDurationMs,sourceIn+Math.max(0,projectDurationMs-startMs));
      if(sourceOut<=sourceIn)throw new Error(track.name+" · 타임라인에 배치할 오디오 구간이 없습니다.");
      const available=sourceOut-sourceIn,fadeIn=Math.min(Math.max(0,Math.round(Number(track.fadeInMs)||0)),available);
      const fadeOut=Math.min(Math.max(0,Math.round(Number(track.fadeOutMs)||0)),Math.max(0,available-fadeIn));
      return {id:"audio_track_"+(index+1),asset_id:track.assetId,start_ms:startMs,source_in_ms:sourceIn,source_out_ms:sourceOut,gain:Math.max(0,Math.min(4,Number(track.gain??1))),fade_in_ms:fadeIn,fade_out_ms:fadeOut};
    });
    const edl={schema:"nexus-edit-decision-list",version:1,timebase:"milliseconds",clips:edlClips,audio_tracks:audioTracks};
    if(transitions.length)edl.transitions=transitions;
    if(gaps.length)edl.gaps=gaps;
    if(projectDurationRaw)edl.project_duration_ms=projectDurationMs;
    return edl;
  }
  async function fetchArtifact(workspaceId,snapshotId){
    const listing=await api().request(pathFor(workspaceId,"/render-artifacts?limit=100"));
    const artifact=(listing.items||[]).find(item=>item.snapshot_id===snapshotId);
    if(!artifact)throw new Error("렌더 완료됐지만 검수 대기 산출물을 찾지 못했습니다.");
    state.artifactId=artifact.artifact_id;
    const blob=await api().requestBlob(pathFor(workspaceId,"/render-artifacts/"+encodeURIComponent(artifact.artifact_id)+"/download"));
    const video=$("timelineServerPreview");
    if(state.outputUrl)URL.revokeObjectURL(state.outputUrl);
    state.outputUrl=URL.createObjectURL(blob);video.removeAttribute("hidden");video.setAttribute("src",state.outputUrl);video.style.display="block";video.load();
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
    clearPrivatePreview();
    $("timelineSubmitRender").disabled=true;$("timelineCheckRender").disabled=true;
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
  function renderAudioTracks(){
    const host=$("timelineAudioTracks");if(!host)return;host.replaceChildren();
    $("timelineAudioStatus").textContent="오디오 트랙 "+state.audios.length+"/8";
    if(!state.audios.length){const empty=document.createElement("small");empty.textContent="최대 8개 독립 오디오 트랙 · 트랙별 시작 위치, Gain, Fade 설정";host.append(empty);return;}
    state.audios.forEach((track,index)=>{
      const row=document.createElement("div");row.className="timeline-audio-track";
      const name=document.createElement("span");name.className="timeline-audio-name";name.textContent=(index+1)+". "+track.name+" · "+track.duration.toFixed(1)+"s";row.append(name);
      for(const [key,label,min,max,step,value] of [
        ["startMs","시작(s)",0,86400,0.1,track.startMs/1000],["sourceInMs","원본 시작(s)",0,86400,0.1,track.sourceInMs/1000],
        ["sourceOutMs","원본 종료(s)",0,86400,0.1,track.sourceOutMs/1000],["gain","Gain",0,4,0.1,track.gain],
        ["fadeInMs","Fade in(s)",0,60,0.1,track.fadeInMs/1000],["fadeOutMs","Fade out(s)",0,60,0.1,track.fadeOutMs/1000]
      ]){
        const labelNode=document.createElement("label");labelNode.textContent=label;
        const input=document.createElement("input");input.type="number";input.min=String(min);input.max=String(max);input.step=String(step);input.value=String(value);
        input.setAttribute("aria-label",track.name+" "+label);
        input.addEventListener("change",()=>{const n=Number(input.value);if(!Number.isFinite(n)||n<min||n>max){input.value=String(value);return;}track[key]=key==="gain"?n:Math.round(n*1000);renderTimelineViews();});
        labelNode.append(input);row.append(labelNode);
      }
      const remove=document.createElement("button");remove.type="button";remove.className="button button-quiet button-small";remove.textContent="트랙 삭제";
      remove.addEventListener("click",()=>{URL.revokeObjectURL(track.url);state.audios.splice(index,1);renderAudioTracks();renderTimelineViews();});
      row.append(remove);host.append(row);
    });
  }
  async function loadAudio(file){
    if(state.audios.length>=8){say("오디오 트랙은 최대 8개까지 추가할 수 있습니다.","error");return;}
    const url=URL.createObjectURL(file),probe=new Audio();probe.preload="metadata";probe.src=url;
    $("timelineAudioStatus").textContent="오디오 길이 확인 중 · "+file.name;
    await new Promise(resolve=>{
      probe.addEventListener("loadedmetadata",()=>{
        if(!Number.isFinite(probe.duration)||probe.duration<=0){URL.revokeObjectURL(url);say(file.name+" · 유효하지 않은 오디오 길이입니다.","error");resolve();return;}
        state.audios.push({file,url,name:file.name,duration:probe.duration,assetId:"",uploadedWorkspaceId:"",serverDurationMs:0,startMs:0,sourceInMs:0,sourceOutMs:Math.round(probe.duration*1000),gain:1,fadeInMs:0,fadeOutMs:0});
        renderAudioTracks();renderTimelineViews();resolve();
      },{once:true});
      probe.addEventListener("error",()=>{URL.revokeObjectURL(url);say(file.name+" · 오디오 메타데이터를 읽을 수 없습니다.","error");resolve();},{once:true});
    });
  }
  function workspaceChanged(){
    const next=currentWorkspace();
    if(next!==state.workspaceId){
      state.workspaceId=next;
      clearPrivatePreview();
      videoClips().forEach(clip=>{clip.assetId="";clip.uploadedWorkspaceId="";clip.serverDurationMs=0;});
      state.audios.forEach(track=>{track.assetId="";track.uploadedWorkspaceId="";track.serverDurationMs=0;});
      $("timelineRenderReview").hidden=true;$("timelineCheckRender").disabled=true;
    }
  }
  function bind(){
    $("timelineCreateWorkspace").addEventListener("click",createWorkspace);
    $("timelineAudioInput").addEventListener("change",async event=>{
      const files=[...(event.target.files||[])];for(const file of files){if(state.audios.length>=8)break;await loadAudio(file);}event.target.value="";
    });
    $("timelineCheckRender").addEventListener("click",async()=>{
      if(!requireEditorContext())return;
      try{await checkRenderStatus();}catch(error){say("렌더 상태 조회 실패 · "+error.message,"error");}
    });
    $("timelineSubmitRender").addEventListener("click",submitRender);
    $("timelineApproveRender").addEventListener("click",()=>decideRender("approved"));
    $("timelineRevisionRender").addEventListener("click",()=>decideRender("revision_requested"));
    $("timelineRejectRender").addEventListener("click",()=>decideRender("rejected"));
    window.addEventListener("nexus:workspace-changed",()=>{workspaceChanged();renderTimelineViews();});
    window.addEventListener("nexus:timeline-updated",renderTimelineViews);
    window.addEventListener("nexus:auth-changed",()=>{clearPrivatePreview();renderTimelineViews();if(!api()?.hasToken())say("API 인증이 초기화되었습니다. 렌더링을 계속하려면 다시 연결하세요.");});
    $("timelineMediaFilter").addEventListener("input",renderMediaShelf);
    $("timelineZoomLevel").addEventListener("input",event=>applyTimelineZoom(event.target.value));
    $("timelineZoomIn").addEventListener("click",()=>applyTimelineZoom(state.zoom+.25));
    $("timelineZoomOut").addEventListener("click",()=>applyTimelineZoom(state.zoom-.25));
    $("timelineZoomFit").addEventListener("click",()=>applyTimelineZoom(1));
    $("timelineProjectDuration").addEventListener("input",renderTimelineViews);
    $("timelineTransitionType").addEventListener("change",renderTimelineViews);
    $("timelineTransitionDuration").addEventListener("change",renderTimelineViews);
    $("timelineScrollLeft").addEventListener("click",()=>scrollTimeline(-1));
    $("timelineScrollRight").addEventListener("click",()=>scrollTimeline(1));
    applyTimelineZoom(state.zoom);
    renderAudioTracks();workspaceChanged();renderTimelineViews();
  }
  if($("timelineEditor")){
    bind();
    window.addEventListener("beforeunload",()=>{state.audios.forEach(track=>URL.revokeObjectURL(track.url));if(state.outputUrl)URL.revokeObjectURL(state.outputUrl);});
    if(!api()?.hasToken())say("편집 미리보기는 로컬에서 가능하며, 서버 렌더링에는 API 주소·토큰·활성 워크스페이스가 필요합니다.");
  }
})();
