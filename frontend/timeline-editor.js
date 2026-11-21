(() => {
  const $ = id => document.getElementById(id);
  const API = () => window.NexusStudioApi;
  const STORAGE = "nexus.editor.assets.v1";
  const WORKSPACE_KEY = "nexus.editor.workspace.v1";
  const state = { workspaces: [], workspaceId: localStorage.getItem(WORKSPACE_KEY) || "", assets: [], files: new Map(), clips: [], titles: [], audio: null, counter: 0, rendering: false, snapshotId: "", artifactId: "", outputUrl: "" };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const apiPath = suffix => "/api/operator/workspaces/" + encodeURIComponent(state.workspaceId) + suffix;
  const say = (message, mode="info") => { const el=$("editorRenderStatus"); if(el){el.textContent=message;el.dataset.state=mode;} };
  const seconds = ms => (Number(ms||0)/1000).toFixed(2);
  const timeLabel = ms => {const s=Math.max(0,Math.round(Number(ms||0)/1000));return Math.floor(s/60)+":"+String(s%60).padStart(2,"0");};
  const bytes = value => {const n=Number(value||0);return n<1024? n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB";};
  const durationOf = asset => Number(asset.media_metadata?.duration_ms || asset.duration_ms || 0);
  const isVideo = asset => asset.media_metadata?.has_video === true || /\.(mp4|mov|m4v|webm|mkv)$/i.test(asset.original_name||"");
  const isAudio = asset => asset.media_metadata?.has_audio === true || /\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(asset.original_name||"");
  const clean = asset => asset.scan_status === "clean" && asset.renderable !== false;
  function persistAssets(){try{localStorage.setItem(STORAGE,JSON.stringify({[state.workspaceId]:state.assets.map(({objectUrl,...item})=>item)}));}catch{}}
  function readAssets(){try{const all=JSON.parse(localStorage.getItem(STORAGE)||"{}");return Array.isArray(all[state.workspaceId])?all[state.workspaceId]:[];}catch{return [];}}
  function recalc(){
    let cursor=0;
    state.clips.forEach(clip=>{clip.start_ms=cursor;clip.end_ms=cursor+(clip.source_out_ms-clip.source_in_ms);cursor=clip.end_ms;});
    state.projectDuration=cursor;
    state.titles=state.titles.filter(item=>item.start_ms>=0&&item.end_ms<=cursor&&item.end_ms>item.start_ms);
    if(state.audio&&state.audio.source_out_ms>durationOf(findAsset(state.audio.asset_id)))state.audio=null;
  }
  function findAsset(id){return state.assets.find(item=>item.asset_id===id);}
  function updateSelects(){
    const video=$("editorVideoSelect"),audio=$("editorAudioSelect");
    if(video)video.innerHTML='<option value="">영상 에셋 선택</option>'+state.assets.filter(a=>clean(a)&&isVideo(a)&&durationOf(a)>0).map(a=>'<option value="'+esc(a.asset_id)+'">'+esc(a.original_name)+'</option>').join("");
    if(audio)audio.innerHTML='<option value="">오디오 에셋 선택</option>'+state.assets.filter(a=>clean(a)&&isAudio(a)&&durationOf(a)>0).map(a=>'<option value="'+esc(a.asset_id)+'">'+esc(a.original_name)+'</option>').join("");
  }
  function renderAssets(){
    const host=$("editorAssetList");if(!host)return;
    host.innerHTML=state.assets.length?state.assets.map(asset=>{
      const status=asset.scan_status==="clean"?"clean":asset.scan_status==="rejected"?"rejected":"pending";
      const label=status==="clean"?"검사 통과":status==="rejected"?"사용 거부":"격리 / 검사 대기";
      const kind=isVideo(asset)?"VIDEO":isAudio(asset)?"AUDIO":"MEDIA";
      const meta=asset.media_metadata||{};
      const detail=[durationOf(asset)?timeLabel(durationOf(asset)):"길이 미확인",meta.video_streams?.[0]?.width&&meta.video_streams?.[0]?.height?meta.video_streams[0].width+"×"+meta.video_streams[0].height:"",bytes(asset.size_bytes||asset.byte_size)].filter(Boolean).join(" · ");
      const objectUrl=asset.objectUrl||"";
      const thumb=objectUrl&&isVideo(asset)?'<video muted playsinline preload="metadata" src="'+esc(objectUrl)+'"></video>':(isAudio(asset)?"♫":"▶");
      const actions=(clean(asset)&&isVideo(asset)?'<button class="editor-mini-button" data-add-video="'+esc(asset.asset_id)+'">타임라인 추가</button>':"")+
        (clean(asset)&&isAudio(asset)?'<button class="editor-mini-button" data-add-audio="'+esc(asset.asset_id)+'">오디오 트랙</button>':"")+
        (status==="pending"?'<button class="editor-mini-button" data-rescan="'+esc(asset.asset_id)+'">검사 재시도</button>':"");
      return '<article class="editor-asset"><div class="editor-asset-thumb">'+thumb+'</div><div class="editor-asset-main"><b title="'+esc(asset.original_name)+'">'+esc(asset.original_name)+'</b><small>'+kind+' · '+esc(detail||"미디어 정보 대기")+'</small><span class="editor-scan '+status+'">'+label+'</span><div class="editor-asset-actions">'+actions+'</div></div></article>';
    }).join(""):'<div class="empty-state">워크스페이스에 미디어가 없습니다. 영상 또는 오디오 파일을 업로드하세요.</div>';
    updateSelects();
  }
  function renderTimeline(){
    recalc();
    const total=Math.max(1,state.projectDuration||1);
    const track=$("editorVideoTrack"),titleTrack=$("editorTitleTrack"),audioTrack=$("editorAudioTrack"),clips=$("editorClipList");
    if(track)track.innerHTML=state.clips.length?state.clips.map((clip,index)=>{
      const asset=findAsset(clip.asset_id),duration=clip.source_out_ms-clip.source_in_ms;
      const width=Math.max(10,duration/total*100);
      return '<div class="editor-track-block" style="flex-basis:'+width+'%;flex-grow:0"><b>'+esc(asset?.original_name||"영상 에셋")+'</b><small>'+timeLabel(duration)+'</small></div>';
    }).join(""):'<div class="editor-track-empty">검사 완료된 영상 에셋을 왼쪽에서 추가하세요.</div>';
    if(titleTrack){
      titleTrack.innerHTML=state.titles.length?state.titles.map(item=>{
        const left=item.start_ms/total*100,width=(item.end_ms-item.start_ms)/total*100;
        return '<div class="editor-title-block" style="left:'+left+'%;width:'+Math.max(3,width)+'%">'+esc(item.text)+'</div>';
      }).join(""):'<div class="editor-track-empty">타이틀 오버레이 없음</div>';
    }
    if(audioTrack)audioTrack.innerHTML=state.audio?'<div class="editor-track-block"><b>'+esc(findAsset(state.audio.asset_id)?.original_name||"오디오")+'</b><small>'+timeLabel(state.audio.source_out_ms-state.audio.source_in_ms)+' · gain '+state.audio.gain.toFixed(1)+'</small></div>':'<div class="editor-track-empty">선택적 오디오 트랙</div>';
    if(clips)clips.innerHTML=state.clips.length?state.clips.map((clip,index)=>{
      const asset=findAsset(clip.asset_id);
      return '<article class="editor-clip-card" data-clip-card="'+esc(clip.id)+'"><div class="editor-clip-card-head"><b>'+String(index+1).padStart(2,"0")+' · '+esc(asset?.original_name||"영상 클립")+'</b><small>'+timeLabel(clip.end_ms-clip.start_ms)+'</small></div><div class="editor-clip-controls"><label>소스 시작 (초)<input type="number" min="0" max="'+seconds(durationOf(asset))+'" step="0.1" value="'+seconds(clip.source_in_ms)+'" data-clip-in="'+esc(clip.id)+'"></label><label>소스 종료 (초)<input type="number" min="0.1" max="'+seconds(durationOf(asset))+'" step="0.1" value="'+seconds(clip.source_out_ms)+'" data-clip-out="'+esc(clip.id)+'"></label></div><div class="editor-clip-card-foot"><button class="editor-mini-button" data-move-up="'+esc(clip.id)+'" '+(index===0?"disabled":"")+'>위로 ↑</button><button class="editor-mini-button" data-move-down="'+esc(clip.id)+'" '+(index===state.clips.length-1?"disabled":"")+'>아래로 ↓</button><button class="editor-mini-button" data-remove-clip="'+esc(clip.id)+'">제거</button></div></article>';
    }).join(""):'<div class="empty-state">아직 타임라인에 영상이 없습니다.</div>';
    const count=$("editorClipCount");if(count)count.textContent=state.clips.length+" VIDEO CLIPS";
    const duration=$("editorDuration");if(duration)duration.textContent=timeLabel(state.projectDuration||0);
    const preview=$("editorPreviewCopy");if(preview)preview.textContent=state.clips.length?state.clips.length+"개 클립 · "+timeLabel(state.projectDuration)+" · EDL v1":"소스 파일을 추가하면 편집 타임라인이 구성됩니다.";
    const render=$("editorRenderButton");if(render)render.disabled=!state.workspaceId||!state.clips.length||state.rendering||state.clips.some(c=>c.source_out_ms<=c.source_in_ms);
  }
  function addVideo(assetId){
    const asset=findAsset(assetId);if(!asset||!clean(asset)||!isVideo(asset))return;
    if(state.clips.length>=20){say("EDL v1은 영상 클립을 최대 20개까지 지원합니다.","error");return;}
    const duration=durationOf(asset);if(!duration){say("서버가 영상 길이를 확인하지 못해 타임라인에 추가할 수 없습니다.","error");return;}
    state.counter+=1;state.clips.push({id:"video_"+state.counter,asset_id:assetId,source_in_ms:0,source_out_ms:duration});
    renderTimeline();say("영상 클립을 타임라인에 추가했습니다.");
  }
  function addAudio(assetId){
    const asset=findAsset(assetId);if(!asset||!clean(asset)||!isAudio(asset))return;
    const duration=durationOf(asset);if(!duration){say("오디오 길이를 확인하지 못했습니다.","error");return;}
    state.audio={id:"audio_1",asset_id:assetId,start_ms:0,source_in_ms:0,source_out_ms:duration,gain:1,fade_in_ms:0,fade_out_ms:0};
    renderTimeline();say("오디오 트랙을 연결했습니다.");
  }
  function edlPayload(){
    recalc();
    const clips=state.clips.map(c=>({id:c.id,type:"video",start_ms:c.start_ms,end_ms:c.end_ms,asset_id:c.asset_id,source_in_ms:c.source_in_ms,source_out_ms:c.source_out_ms}));
    state.titles.forEach((t,index)=>clips.push({id:t.id,type:"title",start_ms:t.start_ms,end_ms:t.end_ms,text:t.text}));
    const audio_tracks=state.audio?[{...state.audio}]:[];
    return {schema:"nexus-edit-decision-list",version:1,timebase:"milliseconds",clips,audio_tracks};
  }
  async function refreshWorkspaces(){
    const client=API();if(!client?.hasToken()){say("편집 기능을 사용하려면 설정에서 API 주소와 운영자 토큰을 연결하세요.");return;}
    try{
      const data=await client.request("/api/operator/workspaces");
      state.workspaces=data.workspaces||[];
      const select=$("editorWorkspaceSelect");
      if(select){
        select.innerHTML=state.workspaces.map(w=>'<option value="'+esc(w.id)+'">'+esc(w.name)+' · '+esc(w.role)+'</option>').join("")||'<option value="">워크스페이스 없음</option>';
        if(state.workspaceId&&state.workspaces.some(w=>w.id===state.workspaceId))select.value=state.workspaceId;
        else if(state.workspaces[0]){state.workspaceId=state.workspaces[0].id;select.value=state.workspaceId;localStorage.setItem(WORKSPACE_KEY,state.workspaceId);}
        else state.workspaceId="";
      }
      if(state.workspaceId)await loadAssets();
      else say("먼저 새 작업공간을 만들어 주세요.");
    }catch(error){say("워크스페이스 조회 실패 · "+error.message,"error");}
  }
  async function loadAssets(){
    state.assets=readAssets();renderAssets();renderTimeline();
    for(const asset of [...state.assets]){
      try{
        const data=await API().request("/api/workspaces/"+encodeURIComponent(state.workspaceId)+"/assets/"+encodeURIComponent(asset.asset_id));
        const latest=data.asset||data;
        Object.assign(asset,{scan_status:latest.scan_status||asset.scan_status,byte_size:latest.byte_size||asset.byte_size,duration_ms:latest.duration_ms||asset.duration_ms,media_metadata:latest.media_metadata||asset.media_metadata,renderable:latest.scan_status==="clean"});
      }catch(error){asset.metadata_error=error.message;}
    }
    persistAssets();renderAssets();
  }
  async function createWorkspace(){
    if(!API()?.hasToken()){say("API 토큰을 먼저 연결하세요.","error");return;}
    const name=$("editorWorkspaceName").value.trim();if(!name){say("작업공간 이름을 입력하세요.","error");return;}
    try{
      const created=await API().request("/api/operator/workspaces",{method:"POST",body:JSON.stringify({name})});
      const id=created.id||created.workspace_id;if(!id)throw new Error("서버가 workspace ID를 반환하지 않았습니다.");
      state.workspaceId=id;localStorage.setItem(WORKSPACE_KEY,id);state.assets=[];state.clips=[];state.titles=[];state.audio=null;
      $("editorWorkspaceName").value="";await refreshWorkspaces();say("작업공간 생성 완료 · "+id,"success");
    }catch(error){say("작업공간 생성 실패 · "+error.message,"error");}
  }
  async function uploadFiles(files){
    if(!state.workspaceId){say("작업공간을 먼저 선택하세요.","error");return;}
    if(!API()?.hasToken()){say("API 토큰을 먼저 연결하세요.","error");return;}
    for(const file of files){
      const ext=(file.name.split(".").pop()||"").toLowerCase();
      if(!["mp4","mov","m4v","webm","mkv","mp3","wav","m4a","aac","flac","ogg"].includes(ext)){say("지원하지 않는 파일 형식 · "+file.name,"error");continue;}
      say("업로드 및 서버 검사 중 · "+file.name);
      try{
        const path=apiPath("/assets")+"?filename="+encodeURIComponent(file.name);
        const data=await API().request(path,{method:"POST",body:file,headers:{"Content-Type":file.type||"application/octet-stream"}});
        const asset={asset_id:data.asset_id,workspace_id:state.workspaceId,original_name:data.original_name||file.name,size_bytes:data.size_bytes||file.size,scan_status:data.scan_status||"pending",scanner_status:data.scanner_status||"unknown",media_metadata:data.media_metadata||null,renderable:!!data.renderable,objectUrl:URL.createObjectURL(file)};
        state.assets=state.assets.filter(item=>item.asset_id!==asset.asset_id);state.assets.unshift(asset);
        persistAssets();renderAssets();
        say(asset.renderable?"업로드·악성코드/미디어 검사 통과 · 타임라인에 추가할 수 있습니다.":"업로드 완료 · 서버 검사 대기 상태이며 통과 전에는 렌더링할 수 없습니다.",asset.renderable?"success":"info");
      }catch(error){say("업로드 실패 · "+file.name+" · "+error.message,"error");}
    }
    $("editorFileInput").value="";
  }
  async function rescan(assetId){
    try{
      const data=await API().request(apiPath("/assets/"+encodeURIComponent(assetId)+"/scan"),{method:"POST"});
      const asset=findAsset(assetId);if(asset){asset.scan_status=data.scan_status;asset.scanner_status=data.scanner_status;asset.media_metadata=data.media_metadata;asset.renderable=!!data.renderable;}
      persistAssets();renderAssets();say(data.renderable?"미디어 검사 통과":"검사 대기 · 렌더링은 보류됩니다.",data.renderable?"success":"info");
    }catch(error){say("재검사 실패 · "+error.message,"error");}
  }
  async function submitRender(){
    if(state.rendering||!state.workspaceId||!state.clips.length)return;
    state.rendering=true;renderTimeline();say("서버 EDL 검증 중 · 렌더링은 아직 시작되지 않았습니다.");
    try{
      const payload=edlPayload();
      const validation=await API().request("/api/timeline/edl/validate",{method:"POST",body:JSON.stringify(payload),headers:{"X-Nexus-Workspace-Id":state.workspaceId}});
      if(!validation.valid)throw new Error("서버 EDL 검증 실패");
      const idempotency="timeline-"+Date.now()+"-"+Math.random().toString(36).slice(2,12);
      const submitted=await API().request(apiPath("/renders"),{method:"POST",body:JSON.stringify({edl:validation.edl,idempotency_key:idempotency})});
      state.snapshotId=submitted.snapshot_id;state.artifactId="";say("렌더 작업 접수 · "+submitted.render_job_id+" · immutable snapshot "+submitted.snapshot_id);
      const started=Date.now();let status=submitted.status||"queued";
      while(Date.now()-started<900000){
        const current=await API().request(apiPath("/renders/"+encodeURIComponent(state.snapshotId)));
        status=current.status;
        if(status==="review_pending"||status==="failed"||status==="cancelled")break;
        say("렌더 작업 "+status+" · "+current.render_job_id+" · 시도 "+current.attempt+"/"+current.max_attempts);
        await new Promise(resolve=>setTimeout(resolve,3000));
      }
      if(status!=="review_pending")throw new Error(status==="failed"?"렌더 작업 실패":"렌더링 대기 시간 초과 · 작업 상태를 새로고침하세요.");
      const listing=await API().request(apiPath("/render-artifacts?limit=100"));
      const artifact=(listing.items||[]).find(item=>item.snapshot_id===state.snapshotId);
      if(!artifact)throw new Error("렌더 완료됐지만 검수 대기 산출물을 찾지 못했습니다.");
      state.artifactId=artifact.artifact_id;
      const blob=await API().requestBlob(apiPath("/render-artifacts/"+encodeURIComponent(state.artifactId)+"/download"));
      if(state.outputUrl)URL.revokeObjectURL(state.outputUrl);
      state.outputUrl=URL.createObjectURL(blob);
      const video=$("editorOutputVideo");video.src=state.outputUrl;video.hidden=false;
      $("editorReviewActions").hidden=false;
      say("렌더 완료 · "+timeLabel(artifact.duration_ms)+" · "+bytes(artifact.byte_size)+" · 검수 대기 상태로 보관 중","success");
    }catch(error){say("렌더 요청 또는 검증 실패 · "+error.message,"error");}
    finally{state.rendering=false;renderTimeline();}
  }
  async function decide(decision){
    if(!state.workspaceId||!state.snapshotId)return;
    const comment=$("editorDecisionComment").value.trim();
    try{
      await API().request(apiPath("/renders/"+encodeURIComponent(state.snapshotId)+"/decision"),{method:"POST",body:JSON.stringify({decision,comment})});
      $("editorReviewActions").hidden=true;
      say(decision==="approved"?"사람 검수 승인 기록 완료 · 공개 게시/업로드는 실행하지 않았습니다.":decision==="rejected"?"검수 반려 기록 완료 · 공개 게시/업로드는 실행하지 않았습니다.":"수정 요청 기록 완료 · 공개 게시/업로드는 실행하지 않았습니다.","success");
    }catch(error){say("검수 결정 실패 · "+error.message,"error");}
  }
  function bind(){
    $("editorCreateWorkspace").addEventListener("click",createWorkspace);
    $("editorWorkspaceSelect").addEventListener("change",async event=>{
      state.workspaceId=event.target.value;localStorage.setItem(WORKSPACE_KEY,state.workspaceId);
      state.clips=[];state.titles=[];state.audio=null;state.snapshotId="";state.artifactId="";
      await loadAssets();say("작업공간 전환 완료");
    });
    $("editorUploadButton").addEventListener("click",()=>$("editorFileInput").click());
    $("editorFileInput").addEventListener("change",event=>uploadFiles([...event.target.files||[]]));
    $("editorAssetList").addEventListener("click",event=>{
      const button=event.target.closest("button");if(!button)return;
      if(button.dataset.addVideo)addVideo(button.dataset.addVideo);
      if(button.dataset.addAudio)addAudio(button.dataset.addAudio);
      if(button.dataset.rescan)rescan(button.dataset.rescan);
    });
    $("editorClipList").addEventListener("click",event=>{
      const button=event.target.closest("button");if(!button)return;
      if(button.dataset.removeClip){state.clips=state.clips.filter(c=>c.id!==button.dataset.removeClip);renderTimeline();}
      if(button.dataset.moveUp||button.dataset.moveDown){
        const id=button.dataset.moveUp||button.dataset.moveDown,index=state.clips.findIndex(c=>c.id===id),next=button.dataset.moveUp?index-1:index+1;
        if(index>=0&&next>=0&&next<state.clips.length){[state.clips[index],state.clips[next]]=[state.clips[next],state.clips[index]];renderTimeline();}
      }
    });
    $("editorClipList").addEventListener("change",event=>{
      const input=event.target,clip=state.clips.find(c=>c.id===input.dataset.clipIn||c.id===input.dataset.clipOut);if(!clip)return;
      const value=Math.round(Number(input.value)*1000);
      if(input.dataset.clipIn)clip.source_in_ms=Math.max(0,Math.min(value,clip.source_out_ms-100));
      if(input.dataset.clipOut)clip.source_out_ms=Math.max(clip.source_in_ms+100,Math.min(value,durationOf(findAsset(clip.asset_id))));
      renderTimeline();
    });
    $("editorAddTitle").addEventListener("click",()=>{
      const text=$("editorTitleText").value.trim(),start=Math.round(Number($("editorTitleStart").value)*1000),end=Math.round(Number($("editorTitleEnd").value)*1000);
      if(!text||!Number.isFinite(start)||!Number.isFinite(end)||end<=start||end>(state.projectDuration||0)){say("타이틀 문구와 유효한 시작·종료 시간(프로젝트 길이 이내)을 입력하세요.","error");return;}
      if(state.clips.length+state.titles.length>=20){say("EDL v1 클립/타이틀 총 개수는 최대 20개입니다.","error");return;}
      state.counter+=1;state.titles.push({id:"title_"+state.counter,type:"title",start_ms:start,end_ms:end,text});
      $("editorTitleText").value="";renderTimeline();say("타이틀 오버레이를 추가했습니다.");
    });
    $("editorAudioSelect").addEventListener("change",event=>{if(event.target.value)addAudio(event.target.value);else{state.audio=null;renderTimeline();}});
    $("editorAudioGain").addEventListener("change",event=>{if(state.audio){state.audio.gain=Math.max(0,Math.min(4,Number(event.target.value)));renderTimeline();}});
    $("editorAudioFadeIn").addEventListener("change",event=>{if(state.audio){state.audio.fade_in_ms=Math.max(0,Math.min(60000,Math.round(Number(event.target.value)*1000)));}});
    $("editorAudioFadeOut").addEventListener("change",event=>{if(state.audio){state.audio.fade_out_ms=Math.max(0,Math.min(60000,Math.round(Number(event.target.value)*1000)));}});
    $("editorRenderButton").addEventListener("click",submitRender);
    $("editorApprove").addEventListener("click",()=>decide("approved"));
    $("editorReject").addEventListener("click",()=>decide("rejected"));
    $("editorRevision").addEventListener("click",()=>decide("revision_requested"));
  }
  async function init(){
    bind();renderAssets();renderTimeline();
    window.addEventListener("nexus:auth-changed",refreshWorkspaces);
    if(API()?.hasToken())await refreshWorkspaces();else say("실제 편집을 시작하려면 우측 상단 설정에서 백엔드 API와 운영자 토큰을 연결하세요.");
  }
  init();
})();
