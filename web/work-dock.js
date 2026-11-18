/* Connect the existing file, preview, plot and job panels to the active scientific step. */
function setWorkExpansion(expanded){
  const layout=q('#workLayout');if(!layout)return;
  dock.expanded=expanded;layout.dataset.expanded=String(expanded);
  const button=q('[data-act="expand-workspace"]',layout);
  button.innerHTML=icon(expanded?'layers':'zoom')+(expanded?'返回分析设置':'展开工作区');
  button.setAttribute('aria-expanded',String(expanded));
  requestAnimationFrame(resizeDockPlot);
}
function focusWorkDock(selector){
  if(S.view!=='work')return;
  const control=q(selector);if(!control)return;
  control.focus({preventScroll:true});control.scrollIntoView({block:'nearest',inline:'nearest'});
}
function handoffTarget(){
  if(S.step===1)return 'index';
  if(S.step===2||(S.step===5&&stageBinding().handoffKind!=='module'))return 'counts';
  return activeModule();
}
const handoffUses={index:'定量参考索引',counts:'捕获计数矩阵',...jobNames};
const preferredProducer={features:'quality',pca:'features',graph:'pca',umap:'graph',leiden:'graph'};
function eligibleJobs(target){
  if(target==='counts')return S.jobs.filter(j=>j.state==='succeeded'&&(j.action==='quantify'||j.has_reads));
  if(target==='index')return S.jobs.filter(j=>j.action==='build_reference'&&j.state==='succeeded');
  const matches=moduleParents(target),first=preferredProducer[target];
  return [...matches.filter(j=>j.action===first),...matches.filter(j=>j.action!==first)];
}
function objectFilename(job){
  return job.action==='quality'?'qc.h5ad':standalone.includes(job.action)?'component.h5ad':'analysis.h5ad';
}
function sourceArchive(project,job,name){
  return api(query('/api/file',{project,path:'runs/'+job+'/'+name}));
}
const archiveCache=new Map();
async function readHandoffArchive(project,job){
  const [io,request]=await Promise.all([api(query('/api/task-io',{project,job})),sourceArchive(project,job,'request.json')]);
  let modules=io.modules.filter(m=>['reference','quantify'].includes(m.module));
  if(!modules.length){
    const receipt=await sourceArchive(project,job,'results/receipt.json');
    modules=(receipt.upstream||[]).map(r=>({module:r.component,capture:r.capture,outputs:{
      raw:r.raw_path?[{path:r.raw_path}]:[],counts:r.filtered_path?[{path:r.filtered_path}]:[],
      index:r.reference_dir?[{path:r.reference_dir}]:[]}}));
  }
  const artifacts=[];
  for(const m of modules){
    if(m.module==='reference'&&m.outputs.index?.[0]?.path){
      artifacts.push({target:'index',path:m.outputs.index[0].path,engine:request.params.quantifier||'starsolo'});
    }else if(m.module==='quantify'&&m.capture){
      const raw=m.outputs.raw?.[0]?.path,filtered=m.outputs.counts?.[0]?.path;
      if(!raw&&!filtered)continue;
      const original=request.libraries.find(l=>l.id===m.capture)||{};
      const metadata=Object.fromEntries(['sample','modality','species','organ','batch','condition'].filter(k=>original[k]).map(k=>[k,original[k]]));
      const lib={id:m.capture,sample:m.capture,...metadata,upstream_capture:m.capture,kind:raw?'raw':'matrix',
        path:raw||filtered,filtered_path:filtered||'',upstream_job:job};
      artifacts.push({target:'counts',path:lib.path,capture:m.capture,lib});
    }
  }
  return {artifacts,reference:request.reference?.id};
}
function getHandoffArchive(project,job){
  const key=project+'/'+job;
  if(!archiveCache.has(key)){
    const value={};
    value.pending=readHandoffArchive(project,job).then(data=>{value.data=data;return data}).catch(err=>{archiveCache.delete(key);throw err});
    archiveCache.set(key,value);
  }
  return archiveCache.get(key).pending;
}
function usableArtifact(a,target){
  return a.target===target&&(target!=='index'||a.engine===param('quantifier','starsolo'));
}
function useButton(job,target,capture='',label='用作本步输入'){
  const bound=target==='counts'?stageLibraries().some(l=>l.upstream_job===job&&l.upstream_capture===capture):
    target!=='index'&&moduleInput().mode==='parent'&&moduleInput().parent===job;
  return btn(bound?'已选作输入':label,'use-output','link','handoff-btn','data-source-job="'+e(job)+'" data-target="'+e(target)+'" data-capture="'+e(capture)+'"');
}
function fileHandoffAction(path,scope){
  if(S.view!=='work'||scope!=='project'||!S.project)return '';
  const match=/^runs\/([^/]+)\//.exec(path);if(!match)return '';
  const job=S.jobs.find(j=>j.id===match[1]&&j.state==='succeeded');if(!job)return '';
  const target=handoffTarget();
  if(target!=='index'&&target!=='counts'){
    if(path!==job.output+'/'+objectFilename(job)||!moduleParents(target).some(j=>j.id===job.id))return '';
    return useButton(job.id,target);
  }
  const data=archiveCache.get(S.project.id+'/'+job.id)?.data;if(!data)return '';
  const absolute=folderPath(S.project.path+'/'+path);
  const item=data.artifacts.find(a=>usableArtifact(a,target)&&[a.path,a.lib?.filtered_path].some(p=>p&&folderPath(p)===absolute));
  return item?useButton(job.id,target,item.capture):'';
}
function warmDirectoryHandoffs(){
  if(S.view!=='work'||S.scope!=='project'||!S.project||!['index','counts'].includes(handoffTarget()))return;
  const parent=/^runs\/([^/]+)(?:\/|$)/.exec(S.dir)?.[1];
  if(!parent||!eligibleJobs(handoffTarget()).some(j=>j.id===parent))return;
  const pid=S.project.id,dir=S.dir;
  if(archiveCache.get(pid+'/'+parent)?.data)return;
  getHandoffArchive(pid,parent).then(()=>{
    if(S.project?.id===pid&&S.scope==='project'&&S.dir===dir&&S.view==='work'){renderExplorer();if(dock.left==='preview')drawDockPreview()}
  }).catch(()=>{});
}
let handoffRequest=0;
const pickedHandoffs=new Map();
async function renderHandoffs(){
  const el=q('#dock-upstream');if(!el||dock.left!=='upstream')return;
  const seq=++handoffRequest,pid=S.project?.id,step=S.step,target=handoffTarget();
  const choices=step===5?['counts',...standalone]:stageModules[step]||[target];
  const selector=choices.length>1?'<label class="field">本步接入用途<select id="handoffTarget">'+options(choices.map(k=>[k,handoffUses[k]]),target)+'</select></label>':'<h3 class="context-label">'+e(handoffUses[target])+'</h3>';
  const jobs=eligibleJobs(target),key=[pid,step,target].join('/');
  const chosen=jobs.find(j=>j.id===pickedHandoffs.get(key))||jobs[0];
  const picker=chosen?'<label class="field">上游任务<select id="handoffSource">'+options(jobs.map(j=>[j.id,(jobNames[j.action]||j.action)+' · '+dateStr(j.created)+' · '+j.id.slice(0,8)]),chosen.id)+'</select></label>':'';
  el.innerHTML='<div class="handoff-panel"><div class="fields">'+selector+picker+'</div><div id="handoffItems" aria-live="polite"></div></div>';
  const host=q('#handoffItems',el);
  if(!chosen){host.innerHTML=empty('link','暂无兼容的上游结果','可使用本步的文件入口，或先完成相应上游任务。');return}
  const active=()=>seq===handoffRequest&&host.isConnected&&pid===S.project?.id&&S.step===step;
  function item(name,detail,capture=''){
    return '<div class="handoff-row">'+icon('file')+'<div><strong>'+e(name)+'</strong><small>'+e(detail)+'</small></div>'+useButton(chosen.id,target,capture)+'</div>';
  }
  const browse=btn('查看来源目录','open-output','folder','','data-path="'+e(chosen.output)+'"');
  if(!['index','counts'].includes(target)){
    host.innerHTML=item(objectFilename(chosen),jobNames[chosen.action]+' → '+handoffUses[target])+browse;return;
  }
  host.textContent='正在读取归档输出…';
  try{
    const data=await getHandoffArchive(pid,chosen.id);if(!active())return;
    const available=data.artifacts.filter(a=>usableArtifact(a,target));
    host.innerHTML=(available.length?available.map(a=>item(a.capture||lastName(a.path),a.target==='index'?a.engine+' · '+a.path:
      (a.lib.filtered_path?'原始与候选细胞计数':'计数矩阵')+' · '+a.lib.sample,a.capture)).join(''):banner('此任务没有与当前用途和引擎匹配的产物。'))+browse;
  }catch(err){if(active())host.innerHTML=banner(err.message,true)}
}
async function useHandoff(el){
  if(S.view!=='work'||!S.project)return;
  const step=S.step,pid=S.project.id,target=el.dataset.target,job=el.dataset.sourceJob;
  if(target!==handoffTarget()||!eligibleJobs(target).some(j=>j.id===job))throw Error('所选产物与当前工作位或模块不匹配。');
  if(target==='counts'){await reuseQuant(job,el.dataset.capture);return}
  if(target==='index'){
    const data=await getHandoffArchive(pid,job);
    if(pid!==S.project?.id||step!==S.step)return;
    const index=data.artifacts.find(a=>usableArtifact(a,target));
    if(!index)throw Error('所选索引与定量引擎不匹配。');
    const field=index.engine==='starsolo'?'star_index':'reference_dir';
    S.draft.params[field]=index.path;
  }else{
    const input=moduleInput();input.mode='parent';input.parent=job;
    if(step===3&&target==='features'&&S.jobs.find(j=>j.id===job)?.action==='quality')stageBinding().qualityParent=job;
  }
  markChanged();await persistInputs();
  if(pid===S.project?.id&&step===S.step){render();toast('已选为'+handoffUses[target]+'的输入 · '+job.slice(0,8))}
}
document.addEventListener('change',ev=>{
  const el=ev.target;
  if(el.id==='handoffSource'){
    pickedHandoffs.set([S.project?.id,S.step,handoffTarget()].join('/'),el.value);renderHandoffs();
  }else if(el.id==='handoffTarget'){
    const value=el.value;
    stageBinding().handoffKind=value==='counts'?'counts':'module';
    if(value!=='counts')stageBinding().module=value;
    persistInputs().catch(()=>{});render();
  }
});

