const $=s=>document.querySelector(s);let current=null;let pollTimer=null;let inputRequestBusy=false;let inputRequestDirty=false;let inputRequestPending=false;let acceptanceVisibleCount=5;let activityVisibleCount=5;let lastAcceptance=null;let lastLiveAgent=null;let lastManagedProcess=null;
function stopProjectPolling(){if(pollTimer){clearInterval(pollTimer);pollTimer=null}}
function startProjectPolling(){if(current&&!inputRequestPending&&!pollTimer)pollTimer=setInterval(refreshState,1800)}
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data={error:t}}if(!r.ok)throw new Error(data.error||r.statusText);return data}
function badge(text,ok){return `<span class="badge" style="border-color:${ok?'#3c8':'#a66'}">${text}</span>`}
async function loadSystem(){try{const s=await api('/api/status');const codexText=s.codex?`Codex ${s.codex_version||''}`:(s.codex_installing?'Codex installing…':'Codex unavailable');$('#systemBadges').innerHTML=badge(`Python ${s.python}`,true)+badge(s.git?'Git':'Git missing',s.git)+badge(codexText,s.codex)+badge(s.opencv&&s.mss?'OpenCV ready':'OpenCV deps missing',s.opencv&&s.mss);const auth=!!s.codex_auth?.authenticated;const loggingIn=!!s.codex_login_in_progress;$('#codexLogin').hidden=auth;$('#codexLogout').hidden=!auth;$('#codexLogin').disabled=loggingIn||s.codex_installing;$('#saveLogin').disabled=auth||loggingIn;$('#codexLogin').textContent=loggingIn?'Signing in…':'Sign in with ChatGPT';$('#codexAuthMessage').textContent=auth?'Authenticated':(loggingIn?(s.codex_login_message||'Complete sign-in in your browser…'):(s.codex_install_error||s.codex_login_message||s.codex_auth?.message||s.codex_install_message||'Sign in required'));}catch(e){$('#systemBadges').textContent=e.message}}
async function loadProjects(selectId=null){const d=await api('/api/projects');const list=$('#projectList');list.innerHTML='';for(const p of d.projects){const b=document.createElement('button');b.className='project-item'+((current===p.id)?' active':'');b.innerHTML=`<strong>${esc(p.name)}</strong><small>${esc(p.agent_status.status||'idle')} • iteration ${p.agent_status.iteration||0}</small>`;b.onclick=()=>selectProject(p.id);list.appendChild(b)}if(selectId)await selectProject(selectId)}
function esc(s=''){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
async function selectProject(id){stopProjectPolling();current=id;inputRequestBusy=false;inputRequestDirty=false;inputRequestPending=false;acceptanceVisibleCount=5;activityVisibleCount=5;lastAcceptance=null;lastLiveAgent=null;lastManagedProcess=null;$('#emptyState').hidden=true;$('#workspace').hidden=false;await refreshState();await loadProjects();startProjectPolling()}
async function refreshState(){if(!current)return;if(inputRequestBusy){inputRequestDirty=true;return}try{const d=await api(`/api/project/${current}/state`);const c=d.config;$('#projectTitle').textContent=c.name;$('#projectGoal').textContent=c.goal;$('#agentBadge').textContent=`Agent: ${d.agent.status}`;$('#iterationBadge').textContent=`Iteration ${d.agent.iteration||0}`;$('#agentMessage').textContent=d.agent.message||d.agent.status;renderLiveTask(d.agent,d.managed_process);$('#cvMessage').textContent=d.cv.message||d.cv.status;$('#researchMode').value=c.research_mode||'deep';$('#internetResearch').checked=!!c.internet_research;$('#cleanCmd').value=c.commands?.clean||'';$('#buildCmd').value=c.commands?.build||'';$('#testCmd').value=c.commands?.test||'';$('#launchCmd').value=c.commands?.launch||'';$('#monitorNum').value=c.visual?.monitor??1;$('#freezeSeconds').value=c.visual?.freeze_seconds??8;renderAcceptance(d.acceptance);renderUserReview(d.user_review);renderUploads(d.uploads);inputRequestPending=!!d.input_request;renderInputRequest(d.input_request);if(inputRequestPending)stopProjectPolling();else startProjectPolling();$('#visualMetrics').textContent=Object.keys(d.visual||{}).length?JSON.stringify(d.visual,null,2):'No visual metrics yet.';if(d.visual?.timestamp){const img=$('#capture');img.hidden=false;img.src=`/api/project/${current}/capture.jpg?t=${Date.now()}`}else $('#capture').hidden=true}catch(e){console.error(e)}}
function activityAge(iso){
 if(!iso)return 'No activity yet';
 const ms=Date.now()-Date.parse(iso);if(!Number.isFinite(ms))return '';
 const sec=Math.max(0,Math.floor(ms/1000));
 if(sec<5)return 'active now';
 if(sec<60)return sec+'s ago';
 const min=Math.floor(sec/60);if(min<60)return min+'m ago';
 const hr=Math.floor(min/60);return hr+'h ago';
}
function liveStateLabel(status){
 if(status==='running')return 'Working';
 if(status==='self-healing')return 'Self-healing';
 if(status==='waiting_for_user')return 'Waiting for you';
 if(status==='paused')return 'Paused';
 if(status==='stopping')return 'Stopping';
 if(status==='complete')return 'Verified complete';
 if(status==='user-complete')return 'Held as done';
 if(status==='blocked'||status==='error')return 'Needs attention';
 if(status==='stopped')return 'Stopped';
 return 'Idle';
}
function renderLiveTask(agent,managed){
 lastLiveAgent=agent;lastManagedProcess=managed;
 const a=agent?.activity||{};
 $('#liveTaskState').textContent=liveStateLabel(agent?.status||'idle');
 $('#liveTaskAge').textContent=activityAge(a.last_activity_at||agent?.last_update);
 const title=a.task||((agent?.status==='running')?'Working…':'Nothing is running right now.');
 $('#liveTaskTitle').innerHTML='<strong>'+esc(title)+'</strong>';
 let detail=a.detail||agent?.message||'Start or resume the autonomous developer to see what GameForge is doing on the computer.';
 if(managed?.running){
   const proc='Managed process active'+(managed.pid?' • PID '+managed.pid:'')+(managed.command?'\n'+managed.command:'');
   detail=detail+'\n\n'+proc;
 }
 $('#liveTaskDetail').textContent=detail;
 const all=(a.history||[]).slice().reverse();
 const shown=all.slice(0,activityVisibleCount);
 let html=shown.length
   ? '<h4>Recent activity</h4>'+shown.map(x=>`<div class="criterion"><strong>${esc(x.task||x.kind||'Activity')}</strong>${x.detail?' — '+esc(x.detail):''}<br><small>${esc(x.at||'')}</small></div>`).join('')
   : '';
 if(all.length>5){
   const remaining=Math.max(0,all.length-shown.length);
   html+='<div class="actions">';
   if(remaining>0)html+=`<button id="showMoreActivity">Show 5 more${remaining?' ('+remaining+' remaining)':''}</button>`;
   if(activityVisibleCount>5)html+='<button id="collapseActivity">Collapse to latest 5</button>';
   html+='</div>';
 }
 $('#liveTaskHistory').innerHTML=html;
 const more=$('#showMoreActivity');if(more)more.onclick=()=>{activityVisibleCount=Math.min(all.length,activityVisibleCount+5);renderLiveTask(lastLiveAgent,lastManagedProcess)};
 const collapse=$('#collapseActivity');if(collapse)collapse.onclick=()=>{activityVisibleCount=5;renderLiveTask(lastLiveAgent,lastManagedProcess);$('#liveTaskHistory').scrollIntoView({block:'nearest'})};
}
function renderInputRequest(r){
 const box=$('#inputRequest');if(!r){box.hidden=true;inputRequestBusy=false;inputRequestPending=false;return}inputRequestPending=true;stopProjectPolling();box.hidden=false;
 $('#inputRequestTitle').textContent=r.title||'GameForge needs input';
 $('#inputRequestMessage').textContent=r.message||'The agent needs additional input.';
 $('#inputRequestWhy').textContent=r.why_user_required||'';
 const c=$('#inputRequestControl');c.innerHTML='';
 if(r.kind==='file'){
   const input=document.createElement('input');input.type='file';input.id='requestedFile';
   if(r.accept_extensions?.length)input.accept=r.accept_extensions.join(',');
   const b=document.createElement('button');b.className='primary';b.textContent='Upload required file';
   const upload=async(file)=>{
     if(!file)return;
     const ext='.'+(file.name.split('.').pop()||'').toLowerCase();
     if(r.accept_extensions?.length&&!r.accept_extensions.map(x=>x.toLowerCase()).includes(ext)){
       $('#inputRequestStatus').textContent='Wrong file type. Expected: '+r.accept_extensions.join(', ');input.value='';return;
     }
     b.disabled=true;input.disabled=true;$('#inputRequestStatus').textContent='Uploading '+file.name+'…';
     try{
       const url=`/api/project/${current}/upload?category=${encodeURIComponent(r.upload_category||'REFERENCE')}&path=${encodeURIComponent(file.name)}&request_id=${encodeURIComponent(r.id||'request')}`;
       const up=await fetch(url,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':file.name},body:file});
       if(!up.ok)throw new Error(await up.text());
       await postAction('input-request/respond',{value:file.name});
       $('#inputRequestStatus').textContent='Received '+file.name+'. Resuming agent…';
       if(r.resume_after_submit!==false)await postAction('agent/resume');
       inputRequestPending=false;startProjectPolling();await endInputRequestInteraction();await refreshState();
     }catch(e){$('#inputRequestStatus').textContent=e.message;b.disabled=false;input.disabled=false;await endInputRequestInteraction();}
   };
   input.addEventListener('pointerdown',()=>beginInputRequestInteraction());
   input.addEventListener('focus',()=>beginInputRequestInteraction());
   input.addEventListener('change',()=>{const file=input.files?.[0];if(file)upload(file);else endInputRequestInteraction()});
   b.onclick=()=>{const file=input.files?.[0];if(file)upload(file);else input.click()};
   c.append(input,b);
 }else if(r.kind==='choice'){
   const sel=document.createElement('select');sel.addEventListener('focus',()=>beginInputRequestInteraction());sel.addEventListener('change',()=>beginInputRequestInteraction());(r.choices||[]).forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;sel.appendChild(o)});
   const b=document.createElement('button');b.className='primary';b.textContent='Submit';b.onclick=()=>submitRequestedValue(r,sel.value);c.append(sel,b);
 }else if(r.kind==='confirm'){
   const b=document.createElement('button');b.className='primary';b.textContent='Confirm and continue';b.onclick=()=>submitRequestedValue(r,true);c.append(b);
 }else{
   const input=document.createElement('input');input.type=r.kind==='url'?'url':'text';input.placeholder=r.placeholder||'Enter requested information';input.addEventListener('focus',()=>beginInputRequestInteraction());input.addEventListener('input',()=>beginInputRequestInteraction());
   const b=document.createElement('button');b.className='primary';b.textContent='Submit';b.onclick=()=>submitRequestedValue(r,input.value);c.append(input,b);
 }}
function beginInputRequestInteraction(){inputRequestBusy=true}
async function endInputRequestInteraction(){inputRequestBusy=false;if(inputRequestDirty){inputRequestDirty=false;await refreshState()}}
async function submitRequestedValue(r,value){beginInputRequestInteraction();try{await postAction('input-request/respond',{value});if(r.resume_after_submit!==false)await postAction('agent/resume');inputRequestPending=false;startProjectPolling();await endInputRequestInteraction();await refreshState()}catch(e){await endInputRequestInteraction();alert(e.message)}}
function renderUserReview(r){
 r=r||{user_done:false,satisfaction:null,feedback:[]};
 const satisfaction=$('#userSatisfaction');
 if(satisfaction && document.activeElement!==satisfaction)satisfaction.value=r.satisfaction==null?'':String(r.satisfaction);
 const done=!!r.user_done;
 $('#markUserDone').hidden=done;
 $('#reopenUserDone').hidden=!done;
 const allFeedback=(r.feedback||[]);
 const pendingCount=allFeedback.filter(x=>!x?.addressed).length;
 if(done){
   const checkpoint=r.done_checkpoint?(' • checkpoint '+r.done_checkpoint.slice(0,10)):'';
   $('#userReviewStatus').textContent='You marked this result done. GameForge is holding this state'+checkpoint+'. You can reopen it at any time.';
 }else if(!$('#userReviewStatus').dataset.local){
   const satisfactionText=r.satisfaction?(' • satisfaction '+r.satisfaction+'/5'):'';
   $('#userReviewStatus').textContent=pendingCount
     ? pendingCount+' feedback work order'+(pendingCount===1?' is':'s are')+' still pending'+satisfactionText+'.'
     : (r.satisfaction?('No pending feedback • satisfaction '+r.satisfaction+'/5'):'Add feedback whenever what you see differs from what you want.');
 }
 const items=allFeedback.slice(-10).reverse();
 $('#userReviewHistory').innerHTML=items.length
   ? '<h4>Recent feedback</h4>'+items.map(x=>{
       const addressed=!!x.addressed;
       const state=addressed?'Addressed':'Pending';
       const resolution=addressed&&x.resolution?`<br><small><strong>Resolution:</strong> ${esc(x.resolution)}</small>`:'';
       const evidence=addressed&&x.evidence?`<br><small><strong>Evidence:</strong> ${esc(x.evidence)}</small>`:'';
       const validation=!addressed&&x.verification_error?`<br><small><strong>Still pending:</strong> ${esc(x.verification_error)}</small>`:'';
       return `<div class="criterion ${addressed?'pass':'pending'}"><strong>${esc(x.category||'feedback')}</strong> — ${esc(x.text||'')}<br><small><strong>${state}</strong> • ${esc(x.created_at||'')}</small>${resolution}${evidence}${validation}</div>`;
     }).join('')
   : '';
}
async function continueAfterReview(){
 try{
   const r=await postAction('agent/resume');
   if(r?.status==='idle'||r?.status==='stopped'||r?.status==='error'||r?.status==='user-complete')await postAction('agent/start');
 }catch(e){
   try{await postAction('agent/start')}catch{}
 }
}
function renderAcceptance(a){
 lastAcceptance=a;
 const box=$('#acceptance');
 const all=a?.criteria||[];
 const shown=all.slice(0,acceptanceVisibleCount);
 let html=`<p><strong>Project complete:</strong> ${a?.project_complete?'YES':'Not yet'}</p>`;
 html+=shown.map(c=>`<div class="criterion ${c.status==='pass'?'pass':'pending'}"><strong>${esc(c.id)}</strong> — ${esc(c.description)}<br><small>${esc(c.status)}${c.evidence?` • ${esc(c.evidence)}`:''}</small></div>`).join('');
 if(all.length>5){
   const remaining=Math.max(0,all.length-shown.length);
   html+='<div class="actions">';
   if(remaining>0)html+=`<button id="showMoreAcceptance">Show 5 more${remaining?' ('+remaining+' remaining)':''}</button>`;
   if(acceptanceVisibleCount>5)html+='<button id="collapseAcceptance">Collapse to first 5</button>';
   html+='</div>';
 }
 box.innerHTML=html;
 const more=$('#showMoreAcceptance');if(more)more.onclick=()=>{acceptanceVisibleCount=Math.min(all.length,acceptanceVisibleCount+5);renderAcceptance(lastAcceptance)};
 const collapse=$('#collapseAcceptance');if(collapse)collapse.onclick=()=>{acceptanceVisibleCount=5;renderAcceptance(lastAcceptance);box.scrollIntoView({block:'nearest'})};
}
function renderUploads(u){$('#uploadList').innerHTML=`<p>${u?.count||0} scanned items</p>`+(u?.items||[]).slice(0,100).map(x=>`<div class="criterion"><strong>${esc(x.path)}</strong><br><small>${x.bytes||0} bytes • ${esc(x.sha256||x.error||'')}</small></div>`).join('')}
async function postAction(action,body={}){if(!current)return;return api(`/api/project/${current}/${action}`,{method:'POST',body:JSON.stringify(body)})}
$('#createBtn').onclick=async()=>{const goal=$('#newGoal').value.trim();if(!goal)return alert('Describe the playable result first.');try{const p=await api('/api/projects/create',{method:'POST',body:JSON.stringify({name:$('#newName').value||'Game Project',goal,research_mode:$('#newResearch').value})});$('#newGoal').value='';await loadProjects(p.id)}catch(e){alert(e.message)}};
$('#refreshBtn').onclick=()=>loadProjects();
for(const [id,act] of [['startAgent','agent/start'],['pauseAgent','agent/pause'],['resumeAgent','agent/resume'],['stopAgent','agent/stop'],['startCv','cv/start'],['stopCv','cv/stop']])$('#'+id).onclick=async()=>{try{await postAction(act);await refreshState()}catch(e){alert(e.message)}};
async function run(which){$('#runOutput').textContent=`Running ${which}...`;try{const r=await postAction(`run/${which}`);$('#runOutput').textContent=(r.output||'')+`\nexit=${r.exit_code} ok=${r.ok}`}catch(e){$('#runOutput').textContent=e.message}}
$('#runBuild').onclick=()=>run('build');
$('#runCleanBuild').onclick=async()=>{
 if(!current)return;
 $('#runOutput').textContent='Cleaning build outputs…';
 try{
   const r=await postAction('run/clean-build',{});
   const cleanOut=r.clean?.output||'';
   const buildOut=r.build?.output||'';
   $('#runOutput').textContent=
     'CLEAN\n'+cleanOut+
     '\n\nBUILD\n'+buildOut+
     `\n\nclean_ok=${!!r.clean?.ok} build_ok=${!!r.build?.ok} overall_ok=${!!r.ok}`;
 }catch(e){$('#runOutput').textContent=e.message}
};
$('#runTest').onclick=()=>run('test');$('#runLaunch').onclick=()=>run('launch');
$('#cleanupArtifacts').onclick=async()=>{
 if(!current)return;
 $('#runOutput').textContent='Cleaning obsolete GameForge artifacts…';
 try{
   const r=await postAction('maintenance/cleanup',{});
   $('#runOutput').textContent=JSON.stringify(r,null,2);
 }catch(e){$('#runOutput').textContent=e.message}
};
$('#checkpoint').onclick=async()=>{try{const r=await postAction('git/checkpoint',{message:'GameForge manual checkpoint'});$('#runOutput').textContent=JSON.stringify(r,null,2)}catch(e){alert(e.message)}};
$('#saveSettings').onclick=async()=>{try{await postAction('config',{research_mode:$('#researchMode').value,internet_research:$('#internetResearch').checked,commands:{clean:$('#cleanCmd').value,build:$('#buildCmd').value,test:$('#testCmd').value,launch:$('#launchCmd').value},visual:{monitor:Number($('#monitorNum').value)||1,interval_sec:1,freeze_seconds:Number($('#freezeSeconds').value)||8,black_mean_threshold:8,region:null,window_title:$('#windowTitle').value}});await refreshState();alert('Saved')}catch(e){alert(e.message)}};
$('#submitFeedback').onclick=async()=>{
 if(!current)return;
 const textValue=$('#userFeedback').value.trim();
 if(!textValue)return alert('Describe what you see and what you want changed.');
 const status=$('#userReviewStatus');status.dataset.local='1';status.textContent='Saving feedback and handing it to the autonomous developer…';
 try{
   const review=await postAction('review/feedback',{text:textValue,category:$('#feedbackCategory').value});
   $('#userFeedback').value='';
   renderUserReview(review);
   await continueAfterReview();
   status.textContent='Feedback saved as a pending work order. The agent must implement and verify it before GameForge can mark it addressed.';
   setTimeout(()=>{delete status.dataset.local},2500);
   await refreshState();
 }catch(e){status.textContent=e.message;delete status.dataset.local}
};
$('#userSatisfaction').onchange=async()=>{
 if(!current)return;
 try{
   const review=await postAction('review/satisfaction',{value:$('#userSatisfaction').value});
   renderUserReview(review);
 }catch(e){alert(e.message)}
};
$('#markUserDone').onclick=async()=>{
 if(!current)return;
 try{
   const review=await postAction('review/done',{done:true});
   renderUserReview(review);
   await refreshState();
 }catch(e){alert(e.message)}
};
$('#reopenUserDone').onclick=async()=>{
 if(!current)return;
 const status=$('#userReviewStatus');status.dataset.local='1';status.textContent='Reopening the saved state and continuing…';
 try{
   const review=await postAction('review/done',{done:false});
   renderUserReview(review);
   await continueAfterReview();
   status.textContent='Reopened. The agent is continuing from the exact saved project state.';
   setTimeout(()=>{delete status.dataset.local},2500);
   await refreshState();
 }catch(e){status.textContent=e.message;delete status.dataset.local}
};
$('#scanUploads').onclick=async()=>{try{const r=await postAction('uploads/scan');renderUploads(r)}catch(e){alert(e.message)}};
$('#uploadBtn').onclick=async()=>{if(!current)return;const files=[...$('#uploadFiles').files];if(!files.length)return alert('Select files.');const cat=$('#uploadCategory').value;for(let i=0;i<files.length;i++){const f=files[i];$('#uploadStatus').textContent=`Uploading ${i+1}/${files.length}: ${f.name}`;const r=await fetch(`/api/project/${current}/upload?category=${encodeURIComponent(cat)}&path=${encodeURIComponent(f.webkitRelativePath||f.name)}`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':f.name},body:f});if(!r.ok)throw new Error(await r.text())}$('#uploadStatus').textContent='Upload complete. Scanning…';const m=await postAction('uploads/scan');renderUploads(m);$('#uploadStatus').textContent='Upload intake complete.'};
$('#refreshLogs').onclick=async()=>{if(!current)return;try{const d=await api(`/api/project/${current}/logs`);$('#logs').innerHTML=d.files.map(f=>`<details class="logbox"><summary>${esc(f.name)}</summary><pre>${esc(f.text)}</pre></details>`).join('')||'<p>No logs yet.</p>'}catch(e){alert(e.message)}};
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('#tab-'+b.dataset.tab).classList.add('active')});
loadSystem();
const requestedProject=new URLSearchParams(location.search).get('project');
loadProjects(requestedProject);

$('#runResearch').onclick=async()=>{if(!current)return;$('#researchOutput').textContent='Researching…';try{const r=await postAction('research/run',{question:$('#researchQuestion').value||'Research whatever is currently most important to completing the playable game goal professionally.'});$('#researchOutput').textContent=r.output||JSON.stringify(r,null,2)}catch(e){$('#researchOutput').textContent=e.message}};
$('#managedLaunch').onclick=async()=>{try{const r=await postAction('process/start',{});$('#processStatus').textContent=JSON.stringify(r,null,2);await refreshState()}catch(e){alert(e.message)}};
$('#managedStop').onclick=async()=>{try{const r=await postAction('process/stop',{});$('#processStatus').textContent=JSON.stringify(r,null,2);await refreshState()}catch(e){alert(e.message)}};
$('#refreshProcesses').onclick=async()=>{if(!current)return;try{const r=await api(`/api/project/${current}/processes`);$('#processList').textContent=r.processes.slice(0,120).map(p=>`${p.pid}\t${p.name}\t${p.exe}`).join('\n')}catch(e){$('#processList').textContent=e.message}};
$('#runInput').onclick=async()=>{try{const seq=JSON.parse($('#inputSequence').value);const r=await postAction('input/replay',{sequence:seq});$('#inputOutput').textContent=JSON.stringify(r,null,2)}catch(e){$('#inputOutput').textContent=e.message}};
$('#analyzeAssets').onclick=async()=>{try{const r=await postAction('assets/analyze',{});$('#assetOutput').textContent=JSON.stringify(r,null,2)}catch(e){$('#assetOutput').textContent=e.message}};
$('#gitStatusBtn').onclick=async()=>{try{const r=await postAction('git/status',{});$('#gitOutput').textContent=`HEAD ${r.head||''}\n\n${r.status||''}\n${r.log||''}`}catch(e){$('#gitOutput').textContent=e.message}};
$('#rollbackBtn').onclick=async()=>{const rev=$('#rollbackRev').value.trim();if(!rev)return alert('Enter a commit hash.');if(!confirm(`Hard-reset this project to ${rev}? A safety checkpoint will be attempted first.`))return;try{const r=await postAction('git/rollback',{revision:rev});$('#gitOutput').textContent=JSON.stringify(r,null,2);await refreshState()}catch(e){$('#gitOutput').textContent=e.message}};

$('#codexLogin').onclick=async()=>{try{$('#codexLogin').disabled=true;$('#codexAuthMessage').textContent='Starting official ChatGPT sign-in…';const r=await api('/api/codex/login',{method:'POST',body:JSON.stringify({save_login:$('#saveLogin').checked})});$('#codexAuthMessage').textContent=r.message||r.error||'Complete sign-in in your browser.';await loadSystem()}catch(e){$('#codexAuthMessage').textContent=e.message;$('#codexLogin').disabled=false}};
$('#codexLogout').onclick=async()=>{try{const r=await api('/api/codex/logout',{method:'POST',body:'{}'});$('#codexAuthMessage').textContent=r.message||'Signed out';await loadSystem()}catch(e){$('#codexAuthMessage').textContent=e.message}};
setInterval(loadSystem,5000);


// Keep the desktop backend tied to the UI lifetime. pagehide also fires on
// reload/navigation, so the backend waits four seconds; a fresh heartbeat
// cancels shutdown after an ordinary reload.
async function sessionHeartbeat(){try{await fetch('/api/session/heartbeat',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true})}catch{}}
sessionHeartbeat();
setInterval(sessionHeartbeat,1500);
window.addEventListener('pagehide',()=>{try{navigator.sendBeacon('/api/session/closing',new Blob(['{}'],{type:'application/json'}))}catch{}});
