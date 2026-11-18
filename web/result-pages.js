const pageNames={work:'/',panes:'/panes',files:'/files',plots:'/plots',runs:'/jobs'};
const jobNames={analysis:'完整分析',quality:'质控与清洗',from_qc:'从清洗对象继续',recluster:'分辨率比较',quantify:'定量',read_qc:'测序质检',build_reference:'参考构建',features:'归一化与高变基因',pca:'主成分与批次诊断',graph:'邻居图',umap:'UMAP 嵌入',leiden:'Leiden 分区'};
const standalone=['features','pca','graph','umap','leiden'];
function moduleParents(name){
  const stages={features:['quality',...standalone],pca:standalone,graph:['pca','graph','umap','leiden'],umap:['graph','umap','leiden'],leiden:['graph','umap','leiden']};
  const allowed=['analysis','from_qc','recluster',...stages[name]];
  return S.jobs.filter(j=>j.state==='succeeded'&&(Array.isArray(j.available_modules)?j.available_modules.includes(name):allowed.includes(j.action)));
}
const visual={job:'',plot:'',items:[],sequence:0,loading:false,error:'',pinned:false};
function resetPageState(){resetDock();resetTree();archiveCache.clear();pickedHandoffs.clear();Object.assign(visual,{job:'',plot:'',items:[],sequence:visual.sequence+1,loading:false,error:'',pinned:false})}
function readRoute(req){
  S.view=Object.keys(pageNames).find(k=>k!=='work'&&pageNames[k]===location.pathname)||
         (['files','plots','runs'].includes(req.get('view'))?req.get('view'):'work');
  if(isDockView())readDockRoute(req);
  if(S.view==='files'||isDockView()){
    S.dir=folderPath(req.get('path'));S.scope=req.get('scope')==='input'?'input':'project';S.scopeLibrary=req.get('library')||'';
  }
  if(S.view==='plots'||isDockView()){visual.job=req.get('job')||'';visual.plot=req.get('figure')||'';visual.pinned=!!visual.job}
  if(S.view==='work'){const n=Number(req.get('step'));S.step=Number.isInteger(n)&&n>=1&&n<=5?n:(S.draft.libraries.length&&S.draft.libraries.every(l=>l.kind==='fastq')?1:2)}
}
function syncRoute(replace=false){
  const fields={project:S.project?.id};
  if(isDockView())Object.assign(fields,dockRoute());
  if(S.view==='files'||isDockView())Object.assign(fields,{path:S.dir,scope:S.scope==='input'?'input':'',library:S.scope==='input'?S.scopeLibrary:''});
  if(S.view==='plots'||isDockView())Object.assign(fields,{job:visual.job,figure:visual.plot});
  if(S.view==='work'&&S.step)fields.step=S.step;
  const next=query(pageNames[S.view]||'/',fields).replace(/\?$/,'');
  if(next!==location.pathname+location.search)history[replace?'replaceState':'pushState']({},'',next);
}
window.addEventListener('popstate',()=>location.reload());
function openPlots(job,figure=''){
  visual.job=job;visual.plot=figure;visual.pinned=true;
  if(isDockView()){setDockTab('right','plots');loadPlots()}else go('plots');
}
function resultURL(path,download=false){return query('/api/file',{project:S.project.id,path,download:download?'1':''})}
async function loadPlots(){
  if(S.view==='plots')renderNav();
  const seq=++visual.sequence, pid=S.project?.id;
  const jobs=S.jobs.filter(j=>j.state==='succeeded');
  const requested=visual.job;
  if(!requested&&jobs.length){
    const withPlots=jobs.find(j=>['analysis','from_qc','recluster','quality','pca','umap','leiden','read_qc'].includes(j.action));
    visual.job=(withPlots||jobs[0]).id;
  }
  visual.items=[];visual.loading=true;visual.error='';renderPlots();
  try{
    if(pid&&visual.job){
      const res=await api(query('/api/plots',{project:pid,job:visual.job}));
      if(seq!==visual.sequence||pid!==S.project?.id)return;
      visual.items=res.items;
      if(!res.items.some(f=>f.id===visual.plot))visual.plot=res.items[0]?.id||'';
    }
  }catch(err){if(seq===visual.sequence)visual.error=err.message}
  finally{if(seq===visual.sequence){visual.loading=false;if(S.view==='plots'||isDockView()){syncRoute(true);renderPlots()}}}
}
function renderPlots(){
  const jobs=S.jobs.filter(j=>j.state==='succeeded');
  const job=S.jobs.find(j=>j.id===visual.job);
  const item=visual.items.find(x=>x.id===visual.plot);
  const picker='<label class="inline">来源任务 <select id="plotJob" class="inline-input">'+options(jobs.map(j=>[j.id,dateStr(j.created)+' · '+(jobNames[j.action]||j.action)+' · '+j.id.slice(0,8)]),visual.job)+'</select></label>';
  let main='';
  if(visual.loading)main=empty('picture','正在读取图表','');
  else if(visual.error)main=banner(visual.error,true);
  else if(!item)main=empty('picture','此任务暂无图表',jobs.length?'选择其他任务或在文件管理器查看产物。':'完成一次质控或分析后，可在此查看结果。');
  else if(item.kind==='interactive')main='<div id="chartMount"></div>';
  else if(item.kind==='partition')main='<div id="partitionMount" class="plot-paper"></div>';
  else if(item.kind==='image')main='<div class="plot-paper"><img id="plotImage" alt="'+e(item.title)+'" src="'+e(resultURL(item.source))+'"></div>';
  else main='<div class="file-reader gallery-report"></div>';
  const tools=item?'<a class="btn" download href="'+e(resultURL(item.source,true))+'">'+icon('install')+(item.kind==='interactive'?'坐标表':item.kind==='partition'?'比较表':'下载')+'</a>'+(item.vector?'<a class="btn" download href="'+e(resultURL(item.vector,true))+'">SVG</a>':''):'';
  const tabs=visual.items.map(x=>'<button type="button" class="plot-tab '+(x.id===visual.plot?'selected':'')+'" data-act="select-plot" data-figure="'+e(x.id)+'">'+icon(x.kind==='interactive'?'layers':x.kind==='report'?'report':'picture')+'<span>'+e(x.title)+'</span></button>').join('');
  const bar=job?btn('查看源目录','open-output','folder','','data-path="'+e(job.output)+'"'):'';
  const target=isDockView()?q('#dock-plots'):$main;
  if(!target)return;
  const controls=isDockView()?'<div class="dock-plot-controls">'+(jobs.length?picker:'')+bar+'</div>':hero('结果可视化',displayProject(),bar)+'<div class="plots-bar">'+(jobs.length?picker:'')+'</div>';
  target.innerHTML=controls+'<div class="plots-shell"><aside class="plot-side"><div class="pane-heading">本次任务的图表</div>'+(isDockView()?'<select id="dockFigure" class="inline-input" aria-label="选择图表">'+options(visual.items.map(f=>[f.id,f.title]),visual.plot)+'</select>':tabs)+'</aside><section class="plot-main"><div class="plot-heading"><h2>'+e(item?.title||'图表')+'</h2><div class="inline">'+tools+'</div></div>'+main+(item?'<footer class="pane-foot"><span class="mono">'+e(item.source.split('/').pop())+'</span><span>任务 '+e(visual.job)+'</span></footer>':'')+'</section></div>';
  const reader=q('.gallery-report',target);
  if(reader)readPreview(reader,{project:S.project.id,path:item.source},null,'',q('.plot-heading .inline',target));
  const host=q('#chartMount');
  if(host)renderEmbedding(visual.job,host).catch(err=>{if(host.isConnected)host.textContent=err.message});
  const partition=q('#partitionMount');
  if(partition)renderPartition(resultURL(item.source),partition).catch(err=>{if(partition.isConnected)partition.textContent=err.message});
}
function renderedBindings(ports){
  const labels=new Map();
  for(const form of [...Object.values(S.boot.tasks||{}),...(S.boot.blocks||[]).map(b=>b.ports)]) {
    for(const p of [...form.inputs,...form.outputs]) labels.set(p.id,p.label);
  }
  const aux={raw_path:'背景计数',filtered_path:'候选计数',corrected_path:'校正计数',clusters_tsv:'粗分群',counts_layer:'计数层',prefix:'FASTQ 前缀'};
  function ref(r){
    const extra=Object.keys(aux).filter(k=>r[k]).map(k=>'<br>'+aux[k]+' <code>'+e(r[k])+'</code>').join('');
    return '<code>'+e(r.path||String(r.value))+'</code>'+(r.selector?' <b>'+e(r.selector)+'</b>':'')+(r.capture?' · '+e(r.capture):'')+extra;
  }
  return Object.entries(ports||{}).map(([name,refs])=>'<div class="port-binding"><strong>'+e(labels.get(name)||name)+'<small class="binding-key">'+e(name)+'</small></strong><div>'+refs.map(ref).join('<br>')+'</div></div>').join('');
}
async function showTaskIO(job){
  const pid=S.project.id,r=await api(query('/api/task-io',{project:pid,job}));
  if(pid!==S.project?.id)return;
  const prefix=r.schema.endsWith('/legacy')?banner('历史作业按原始收据展示任务级输入和产物。'):r.state!=='succeeded'?banner('任务状态为 '+(jobLabels[r.state]||r.state)+'。当前可检查已登记的输入。'):'';
  const download=r.schema==='plant-task-io/1'?'<a class="btn" download href="'+e(resultURL('runs/'+job+'/results/task-io.json',true))+'">下载完整接口清单</a>':'';
  const partial=r.partial_outputs?.length?'<details class="accordion"><summary>已写入的中间文件（未验收）</summary>'+renderedBindings({files:r.partial_outputs})+'</details>':'';
  const content=prefix+download+partial+(r.parent_job?'<p>父任务 <code>'+e(r.parent_job)+'</code></p>':'')+'<h3>任务输入</h3>'+renderedBindings(r.inputs)+'<details class="accordion"><summary>任务输出与完整文件清单</summary>'+renderedBindings(r.outputs)+'</details>'+r.modules.map(m=>'<details class="accordion"><summary>'+e(S.boot.blocks.find(x=>x.id===m.module)?.title||m.module)+(m.capture?' · '+e(m.capture):'')+'</summary>'+(m.engine?'<p class="hint">'+e(m.engine)+' · 接口 v'+e(m.version)+'</p>':'')+'<h4>输入</h4>'+renderedBindings(m.inputs)+'<h4>输出</h4>'+renderedBindings(m.outputs)+'<h4>运行参数</h4><pre class="preview-text">'+e(JSON.stringify(m.parameters,null,2))+'</pre>'+(m.observed&&Object.keys(m.observed).length?'<h4>实测指标</h4><pre class="preview-text">'+e(JSON.stringify(m.observed,null,2))+'</pre>':'')+'</details>').join('');
  modalShow('任务输入与输出',content,'io',true);
}
async function handleWorkspaceAction(act,el){
  switch(act){
    case 'select-plot':visual.plot=el.dataset.figure;syncRoute();renderPlots();break;
    case 'mkdir-dialog':fileOperation('mkdir');break;
    case 'copy-entry':fileOperation('copy',el.dataset.path);break;
    case 'up-dir':openDir(S.dir.split('/').slice(0,-1).join('/'));break;
    case 'reveal-dir':await api('/api/files/reveal',fileArgs(S.dir));break;
    case 'copy-dir-path':await navigator.clipboard.writeText(S.dirAbsolute);toast('已复制目录路径');break;
    case 'expand-dir':{
      const dir=el.dataset.path;
      if(expandedDirs.has(dir))expandedDirs.delete(dir);
      else {expandedDirs.add(dir);if(!explorerTree.has(dir))await getTree(dir)}
      if(q('#folderTree'))q('#folderTree').innerHTML=folderTreeHTML();break;
    }
    default:return false;
  }
  return true;
}
document.addEventListener('change',ev=>{
  if(ev.target.id==='dockFigure'){visual.plot=ev.target.value;syncRoute();renderPlots()}
  if(ev.target.id==='plotJob')openPlots(ev.target.value);
  if(ev.target.id==='fileOrder'){fileOrder=ev.target.value;renderExplorer()}
});

