/* Offline interaction tests for the dashboard's non-destructive refresh.
 * Uses Node's built-in test runner; no network/browser dependencies. */
'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const webDir = path.resolve(__dirname, '../web');
const uiSource = fs.readFileSync(path.join(webDir, 'ui_refresh.js'), 'utf8');
const appSource = fs.readFileSync(path.join(webDir, 'app.js'), 'utf8');

class FakeElement {
  constructor(id='', tag='div') {
    this.id=id;this.tagName=tag.toUpperCase();this.type=tag==='select'?'select-one':'text';
    this.value='';this.checked=false;this.hidden=false;this.children=[];this.dataset={};
    this.textContent='';this.scrollTop=0;this.scrollLeft=0;this.isConnected=true;this.open=false;
    this._html='';this._details=[];this.htmlWrites=0;this.srcWrites=0;this._src='';
    this.classList={add(){},remove(){}};
    this.listeners={};
  }
  get innerHTML(){return this._html}
  set innerHTML(value){
    this._html=String(value);this.htmlWrites++;this._details=[];
    for(const match of this._html.matchAll(/<details\b[^>]*data-preserve-key="([^"]+)"/g)){
      this._details.push({
        key:match[1],open:false,
        getAttribute(name){return name==='data-preserve-key'?this.key:null}
      });
    }
    this.children=[];
  }
  get src(){return this._src}
  set src(value){this._src=value;this.srcWrites++}
  append(...nodes){this.children.push(...nodes)}
  appendChild(node){this.children.push(node);return node}
  replaceChildren(...nodes){this.children=[...nodes];this._html='';this._details=[];this.htmlWrites++}
  addEventListener(type,handler){(this.listeners[type]??=[]).push(handler)}
  contains(node){return this===node||this.children.some(child=>child===node||child.contains?.(node))}
  querySelectorAll(selector){return selector==='details[data-preserve-key]'?this._details:[]}
  setAttribute(name,value){this[name]=value}
  getAttribute(name){return this[name]||null}
  matches(selector){return selector.includes(this.tagName.toLowerCase())}
  scrollIntoView(){}
  remove(){this.isConnected=false}
  select(){}
}

function makeDocument(){
  const nodes=new Map(),listeners=new Map();
  let selected=null;
  const doc={
    activeElement:null,hidden:false,body:new FakeElement('body'),
    getElementById(id){return nodes.get(id)||null},
    querySelector(selector){
      if(!selector.startsWith('#'))return null;
      const id=selector.slice(1);
      if(!nodes.has(id))nodes.set(id,new FakeElement(id,
        /Transport|Effort|Mode|Category|Satisfaction/.test(id)?'select':
        /McpServers|AcpCommand|Feedback|Instruction|Goal|Sequence/.test(id)?'textarea':'div'));
      return nodes.get(id);
    },
    querySelectorAll(){return []},
    createElement(tag){return new FakeElement('',tag)},
    getSelection(){
      return selected?{
        isCollapsed:false,rangeCount:1,anchorNode:selected,focusNode:selected,
        getRangeAt(){return {intersectsNode(node){return node===selected||node.contains?.(selected)}}}
      }:{isCollapsed:true,rangeCount:0};
    },
    addEventListener(type,handler){(listeners.get(type)||listeners.set(type,[]).get(type)).push(handler)},
    emit(type,target){
      for(const fn of listeners.get(type)||[])fn({type,target});
    },
    chooseSelection(node){selected=node},
    execCommand(){return true}
  };
  return doc;
}
function makeUi(){
  const doc=makeDocument();
  const copied=[];
  const win={document:doc,navigator:{clipboard:{async writeText(value){copied.push(value)}}}};
  vm.runInNewContext(uiSource,{window:win});
  return {ui:win.GameForgeUI,doc,win,copied};
}

test('unchanged HTML preserves DOM and expanded detail state on every poll',()=>{
  const {ui}=makeUi();
  const box=new FakeElement('queue');
  assert.equal(ui.setHtml(box,'<details data-preserve-key="one"><summary>View</summary>A</details>'),true);
  assert.equal(box.htmlWrites,1);
  box._details[0].open=true;
  assert.equal(ui.setHtml(box,'<details data-preserve-key="one"><summary>View</summary>A</details>'),false);
  assert.equal(box.htmlWrites,1);
  assert.equal(box._details[0].open,true);
  box.scrollTop=54;
  ui.setHtml(box,'<details data-preserve-key="one"><summary>View</summary>B</details>');
  assert.equal(box._details[0].open,true);
  assert.equal(box.scrollTop,54);
  assert.equal(box.htmlWrites,2);
});

test('a temporary error message cannot poison the HTML render cache',()=>{
  const {ui}=makeUi();
  const box=new FakeElement('systemBadges');
  ui.setHtml(box,'<span class="badge">Online</span>');
  const initialWrites=box.htmlWrites;
  ui.setText(box,'Offline');
  assert.equal(ui.setHtml(box,'<span class="badge">Online</span>'),true);
  assert.equal(box.htmlWrites,initialWrites+1);
});

test('text selection survives a changing live activity stream until deselected',()=>{
  const {ui,doc}=makeUi();
  const text=new FakeElement('activity');
  assert.equal(ui.setText(text,'initial live text'),true);
  doc.chooseSelection(text);
  assert.equal(ui.setText(text,'updated live text'),false);
  assert.equal(text.textContent,'initial live text');
  doc.chooseSelection(null);
  assert.equal(ui.setText(text,'updated live text'),true);
  assert.equal(text.textContent,'updated live text');
});

test('selection inside expanded queue details blocks destructive rerender',()=>{
  const {ui,doc}=makeUi();
  const box=new FakeElement('queue');
  ui.setHtml(box,'<details data-preserve-key="abc">One</details>');
  const oldWrites=box.htmlWrites;
  doc.chooseSelection(box);
  assert.equal(ui.setHtml(box,'<details data-preserve-key="abc">Two</details>'),false);
  assert.equal(box.htmlWrites,oldWrites);
  doc.chooseSelection(null);
  assert.equal(ui.setHtml(box,'<details data-preserve-key="abc">Two</details>'),true);
});

test('settings stay user-edited even after focus leaves the native dropdown',()=>{
  const {ui,doc}=makeUi();
  const transport=doc.querySelector('#agentTransport');
  const effort=doc.querySelector('#agentCodexEffort');
  ui.trackSettings(['agentTransport','agentCodexEffort']);
  ui.setField(transport,'auto');
  ui.setField(effort,'medium');
  transport.value='acp';
  doc.emit('change',transport);
  effort.value='high';
  doc.emit('change',effort);
  doc.activeElement=null;
  ui.setField(transport,'exec');
  ui.setField(effort,'low');
  assert.equal(transport.value,'acp');
  assert.equal(effort.value,'high');
  ui.markSaved({agentTransport:'acp',agentCodexEffort:'high'});
  ui.setField(transport,'exec');
  assert.equal(transport.value,'exec');
  ui.setField(effort,'low');
  assert.equal(effort.value,'low');
});

test('new edits during settings save remain unsaved and are never overwritten',()=>{
  const {ui,doc}=makeUi();
  const field=doc.querySelector('#cleanCmd');
  ui.trackSettings(['cleanCmd']);
  ui.setField(field,'npm run clean');
  field.value='make clean';
  doc.emit('input',field);
  const saveSent='make clean';
  field.value='cmake --build build --target clean';
  doc.emit('input',field);
  ui.markSaved({cleanCmd:saveSent});
  ui.setField(field,'npm run clean');
  assert.equal(field.value,'cmake --build build --target clean');
  ui.resetProject();
  ui.setField(field,'new project clean');
  assert.equal(field.value,'new project clean');
});

test('focused agent input controls are never recreated while the user is typing',()=>{
  const {ui,doc}=makeUi();
  const control=new FakeElement('inputRequestControl');
  const input=new FakeElement('pendingAnswer','textarea');
  control.append(input);
  doc.activeElement=input;
  assert.equal(ui.setHtml(control,'<input id="replacement">'),false);
  assert.equal(control.children[0],input);
  doc.activeElement=null;
  assert.equal(ui.setHtml(control,'<input id="replacement">'),true);
});

test('copy uses clipboard API without disturbing existing text selection',async()=>{
  const {ui,doc,copied}=makeUi();
  const source=new FakeElement('text');
  source.textContent='Agent diagnostics are readable.';
  doc.chooseSelection(source);
  await ui.copyText(source.textContent);
  assert.deepEqual(copied,['Agent diagnostics are readable.']);
  assert.equal(doc.getSelection().isCollapsed,false);
});

test('live app uses single-flight polling, stable agent questions and capture timestamps',async()=>{
  const doc=makeDocument();
  const win={document:doc,navigator:{clipboard:{async writeText(){}}},addEventListener(){}};
  const payload={
    config:{name:'Test Project',goal:'Demo',agent:{transport:'auto',model:'',effort:''},
            commands:{clean:'make clean'},visual:{monitor:1,freeze_seconds:8}},
    agent:{status:'running',transport:'app-server',iteration:10,steering_available:true,
           activity:{task:'Working',detail:'unchanged work',last_activity_at:'2026-10-15T20:00:00Z',history:[]}},
    acceptance:{iteration:250,project_complete:false,criteria:[]},
    iteration_progress:{agent_iteration:10,last_evidence_iteration:9,project_progress_iteration:250},
    live_queue:{queued:[],in_progress:[],implemented:[],delivered_to_agent:[],recent:[]},
    user_review:{satisfaction:'2',feedback:[]},
    input_request:{id:'q1',protocol:'codex-app-server',kind:'choice',
      questions:[{id:'choice1',header:'Choose',question:'Which style?',options:[{label:'A'},{label:'B'}]}]},
    visual:{timestamp:'capture-001'}
  };
  let pendingStates=0,concurrent=0,maxConcurrent=0,stateRequests=0;
  const fetch=async url=>{
    let body;
    if(url==='/api/status')body={python:'3.12',git:true,codex:false,opencv:true,mss:true};
    else if(url==='/api/projects')body={projects:[{id:'demo',name:'Demo',agent_status:{status:'running',iteration:10}}]};
    else if(url==='/api/project/demo/state'){
      stateRequests++;concurrent++;maxConcurrent=Math.max(concurrent,maxConcurrent);
      if(pendingStates)await new Promise(resolve=>setTimeout(resolve,8));
      body=payload;concurrent--;
    }else body={};
    return {ok:true,async text(){return JSON.stringify(body)}};
  };
  const context=vm.createContext({
    document:doc,window:win,navigator:win.navigator,fetch,URLSearchParams,
    location:{search:'?project=demo'},
    setTimeout(){return 1},clearTimeout(){},setInterval(){return 1},clearInterval(){},
    alert(){},confirm(){return true},console,Blob:class{},Date
  });
  vm.runInContext(uiSource,context);
  vm.runInContext(appSource,context);
  for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));
  const settings=doc.querySelector('#agentTransport');
  const effort=doc.querySelector('#agentCodexEffort');
  const questions=doc.querySelector('#inputRequestControl');
  assert.ok(questions.children.length,'Initial agent questions rendered');
  const questionControls=questions.children;
  const capture=doc.querySelector('#capture');
  const initialCaptures=capture.srcWrites;
  const queue=doc.querySelector('#liveQueueList');
  const initialQueueWrites=queue.htmlWrites;
  const answer=questions.children[0].children.find(child=>child.tagName==='SELECT');
  assert.ok(answer,'Question select exists');
  answer.value='B';
  doc.activeElement=answer;
  settings.value='acp';doc.emit('change',settings);
  effort.value='high';doc.emit('change',effort);
  payload.agent.activity.detail='new activity';
  await vm.runInContext('refreshState()',context);
  assert.equal(settings.value,'acp');
  assert.equal(effort.value,'high');
  assert.equal(questions.children[0],questionControls[0]);
  assert.equal(answer.value,'B','Open question selection is preserved');
  assert.equal(queue.htmlWrites,initialQueueWrites,'Unchanged work-order HTML is never replaced');
  assert.equal(capture.srcWrites,initialCaptures,'A repeated capture timestamp does not reload the image');
  payload.visual.timestamp='capture-002';
  await vm.runInContext('refreshState()',context);
  assert.equal(capture.srcWrites,initialCaptures+1,'A new capture timestamp refreshes the image exactly once');
  doc.activeElement=null;
  doc.chooseSelection(doc.querySelector('#liveTaskDetail'));
  await vm.runInContext('refreshState()',context);
  const beforeText=doc.querySelector('#liveTaskDetail').textContent;
  payload.agent.activity.detail='another update';
  await vm.runInContext('refreshState()',context);
  assert.equal(doc.querySelector('#liveTaskDetail').textContent,beforeText,'Text remains selected');
  doc.chooseSelection(null);
  await vm.runInContext('refreshState()',context);
  assert.match(doc.querySelector('#liveTaskDetail').textContent,/another update/);
  payload.input_request=null;
  await vm.runInContext('refreshState()',context);
  assert.equal(doc.querySelector('#inputRequest').hidden,true,'Resolved question disappears');
  assert.equal(questions.children.length,0,'Resolved question controls are retired');
  pendingStates=1;
  const first=vm.runInContext('refreshState()',context);
  const second=vm.runInContext('refreshState()',context);
  await Promise.all([first,second]);
  await new Promise(resolve=>setTimeout(resolve,25));
  assert.equal(maxConcurrent,1,'Dashboard never makes concurrent state requests');
  assert.ok(stateRequests>=4);
});
