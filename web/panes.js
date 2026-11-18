/* The two tab groups share the project and operate on independent file and plot selections. */
const dockTabs={left:[['files','文件','folder'],['preview','预览','file']],right:[['plots','图表','picture'],['jobs','任务','history']]};
function isDockView(){return S.view==='panes'||S.view==='work'}
function tabsFor(side){
  if(S.view==='work'&&side==='left')return [...dockTabs.left,['upstream','上游输出','link'],['stage','本步文件','files']];
  return dockTabs[side];
}
const dock={left:'files',right:'plots',focus:'',preview:null,request:0,ratio:44,tree:false,expanded:false};
try{const width=Number(localStorage.getItem('plant-sc-workbench.split'));if(width>=30&&width<=70)dock.ratio=width}catch{}

function resetDock(){
  Object.assign(dock,{left:'files',right:'plots',focus:'',preview:null,request:dock.request+1,tree:false,expanded:false});
}
function readDockRoute(req){
  dock.left=tabsFor('left').some(([key])=>key===req.get('left'))?req.get('left'):(req.has('preview')?'preview':'files');
  dock.right=req.get('right')==='jobs'?'jobs':'plots';
  dock.focus=['left','right'].includes(req.get('focus'))?req.get('focus'):'';
  const path=folderPath(req.get('preview'));
  dock.preview=path?{path,scope:req.get('previewScope')==='input'?'input':'project',library:req.get('previewLibrary')||''}:null;
}
function dockRoute(){
  return {left:dock.left==='files'&&!dock.preview?'':dock.left,right:dock.right==='plots'?'':dock.right,focus:dock.focus,
          preview:dock.preview?.path,previewScope:dock.preview?.scope==='input'?'input':'',previewLibrary:dock.preview?.library};
}
function dockGroup(side){
  const tabs=tabsFor(side);
  const buttons=tabs.map(([key,title,ic])=>'<button type="button" role="tab" id="tab-'+key+'" data-side="'+side+'" data-dock-tab="'+key+'" aria-controls="dock-'+key+'">'+icon(ic)+title+'</button>').join('');
  const panels=tabs.map(([key])=>'<section class="dock-panel" id="dock-'+key+'" role="tabpanel" tabindex="0" aria-labelledby="tab-'+key+'"></section>').join('');
  return '<div class="dock-group" id="group-'+side+'"><div class="dock-nav"><div role="tablist" aria-label="'+(side==='left'?(S.view==='work'?'项目文件与分析输入':'文件与预览'):'图表与任务')+'">'+buttons+'</div><button type="button" class="dock-focus" data-dock-focus="'+side+'"></button></div>'+panels+'</div>';
}
function applyDock(){
  const grid=q('#dockGrid');if(!grid)return;
  grid.dataset.focus=dock.focus;grid.style.setProperty('--split',dock.ratio+'%');
  grid.dataset.tree=dock.tree?'open':'closed';
  q('#dockDivider').setAttribute('aria-valuenow',Math.round(dock.ratio));
  for(const side of ['left','right']){
    const focus=q('[data-dock-focus="'+side+'"]');
    const enlarged=dock.focus===side;
    focus.innerHTML=icon(enlarged?'layers':'zoom')+(enlarged?'还原':'放大');
    focus.setAttribute('aria-label',(enlarged?'还原':'放大')+(side==='left'?'文件分区':'结果分区'));
    for(const [key] of tabsFor(side)){
      const tab=q('#tab-'+key),active=dock[side]===key;
      tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
      q('#dock-'+key).hidden=!active;
    }
  }
}
function setDockTab(side,tab,route=true){
  if(!tabsFor(side)?.some(([key])=>key===tab))return;
  dock[side]=tab;
  if(dock.focus&&dock.focus!==side)dock.focus='';
  applyDock();
  if(route)syncRoute();
  if(tab==='jobs')drawDockJobs();
  if(tab==='upstream')renderHandoffs();
  if(tab==='stage')refreshStageFiles();
  if(tab==='plots')requestAnimationFrame(resizeDockPlot);
}
function resizeDockPlot(){
  if(!window.Plotly||dock.right!=='plots'||dock.focus==='left')return;
  const chart=q('#dock-plots .js-plotly-plot');
  if(chart?.clientWidth)Plotly.Plots.resize(chart).catch(()=>{});
}
let dockObserver;
function mountDock(host){
  const project=S.project?.id||'';
  if(host.dataset.project===project&&host.querySelector('#dockGrid')){applyDock();return false}
  host.dataset.project=project;
  dockObserver?.disconnect();
  if(!tabsFor('left').some(([key])=>key===dock.left))dock.left='files';
  host.innerHTML='<div class="dock-grid" id="dockGrid">'+dockGroup('left')+
    '<div tabindex="0" role="separator" aria-label="调整分区宽度" aria-orientation="vertical" aria-valuemin="30" aria-valuemax="70" id="dockDivider"></div>'+dockGroup('right')+'</div>';
  if(S.view==='work')q('#dock-stage').innerHTML=stageFilesPanel();
  applyDock();renderExplorer();renderPlots();drawDockJobs();drawDockPreview();
  dockObserver=new ResizeObserver(resizeDockPlot);dockObserver.observe(q('#group-right'));
  return true;
}
function renderDock(){
  if(!q('#globalDock'))$main.innerHTML=hero('分区工作区',displayProject())+'<div id="globalDock"></div>';
  mountDock(q('#globalDock'));
}
async function loadDock(){
  renderNav();renderDock();
  await Promise.all([loadFiles(),loadPlots()]);
}
function drawDockJobs(){
  const target=q('#dock-jobs');if(!target||dock.right!=='jobs')return;
  target.innerHTML='<div class="dock-actions">'+btn('刷新','refresh-jobs','refresh')+'</div>'+
    (S.jobs.length?'<div class="dock-joblist">'+S.jobs.map(j=>jobHTML(j)).join('')+'</div>':empty('history','还没有运行记录','提交分析后可以在此检查进度。'));
}
function updateDockJobs(previous){
  if(dock.right==='jobs'&&(activeJobs().length||previous!==S.jobs.map(j=>j.state+j.id).join('|')))drawDockJobs();
  if(S.view==='work'&&dock.left==='upstream'&&previous!==S.jobs.map(j=>j.state+j.id).join('|'))renderHandoffs();
  if(!visual.job&&!visual.loading&&S.jobs.some(j=>j.state==='succeeded'))loadPlots();
  else if(previous!==S.jobs.map(j=>j.state+j.id).join('|')){
    const picker=q('#plotJob');
    if(picker)picker.innerHTML=options(S.jobs.filter(j=>j.state==='succeeded').map(j=>[j.id,dateStr(j.created)+' · '+(jobNames[j.action]||j.action)+' · '+j.id.slice(0,8)]),visual.job);
  }
}
async function openDockFile(path,scope=S.scope,library=S.scopeLibrary,fragment=''){
  dock.preview={path,scope,library:scope==='input'?library:''};
  setDockTab('left','preview');
  await drawDockPreview(fragment);
}
async function drawDockPreview(fragment=''){
  const el=q('#dock-preview'),file=dock.preview,request=++dock.request;
  if(!el)return;
  if(!file||!S.project){el.innerHTML=empty('file','选择文件以预览','在文件页签中选择报告、表格、分析对象或其他文件。');return}
  const args={project:S.project.id,...file};
  const title=lastName(file.path);
  const toolbar='<div class="dock-preview-head"><strong>'+e(title)+'</strong><div class="inline"><span data-preview-input>'+fileHandoffAction(file.path,file.scope)+'</span><a class="btn" download href="'+e(query('/api/file',{...args,download:1}))+'">'+icon('install')+'下载</a></div></div>';
  const footer='<div class="pane-foot">'+e(file.path)+'</div>';
  if(request!==dock.request)return;
  el.innerHTML=toolbar+'<div class="file-reader"></div>'+footer;
  await readPreview(q('.file-reader',el),args,(path,hash)=>openDockFile(path,file.scope,file.library,hash),fragment,q('.dock-preview-head .inline',el));
}
function splitWidth(value,persist=false){
  dock.ratio=Math.max(30,Math.min(70,value));applyDock();
  if(persist){try{localStorage.setItem('plant-sc-workbench.split',String(dock.ratio))}catch{}}
}
document.addEventListener('click',ev=>{
  const button=ev.target.closest('[data-dock-tab],[data-dock-focus],[data-dock-tree]');
  if(!button)return;
  if(button.dataset.dockTab)setDockTab(button.dataset.side,button.dataset.dockTab);
  else if(button.hasAttribute('data-dock-tree')){
    dock.tree=!dock.tree;applyDock();button.setAttribute('aria-expanded',String(dock.tree));
  }else{const side=button.dataset.dockFocus;dock.focus=dock.focus===side?'':side;applyDock();syncRoute()}
});
document.addEventListener('keydown',ev=>{
  if(ev.target.id==='dockDivider'){
    const value={ArrowLeft:dock.ratio-3,ArrowRight:dock.ratio+3,Home:30,End:70}[ev.key];
    if(value!==undefined){ev.preventDefault();splitWidth(value,true)}
  }else if(ev.target.dataset.dockTab&&['ArrowLeft','ArrowRight','Home','End'].includes(ev.key)){
    ev.preventDefault();const side=ev.target.dataset.side,keys=tabsFor(side).map(([k])=>k),idx=keys.indexOf(dock[side]);
    const tab=ev.key==='Home'?keys[0]:ev.key==='End'?keys.at(-1):keys[(idx+(ev.key==='ArrowLeft'?keys.length-1:1))%keys.length];
    setDockTab(side,tab);q('#tab-'+tab).focus();
  }
});
document.addEventListener('pointerdown',ev=>{
  const handle=ev.target;if(handle.id!=='dockDivider')return;
  ev.preventDefault();handle.focus();handle.setPointerCapture(ev.pointerId);
  const move=e=>{const r=q('#dockGrid').getBoundingClientRect();splitWidth(100*(e.clientX-r.left)/r.width)};
  const stop=()=>{splitWidth(dock.ratio,true);handle.removeEventListener('pointermove',move);handle.removeEventListener('lostpointercapture',stop)};
  handle.addEventListener('pointermove',move);handle.addEventListener('lostpointercapture',stop);
});

