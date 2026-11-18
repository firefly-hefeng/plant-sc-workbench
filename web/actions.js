const busyButtons = new Set();
let pendingAfterCreate=null;
let nextQC=0;
function markChanged(){S.preview=null;++nextQC;save();const region=q('#qcPreview');if(region)region.innerHTML=''}
function dataSpec(action='analysis',libraries=S.draft.libraries){
  const libs=libraries.map(l=>({...l,id:l.upstream_capture||l.id}));
  if(new Set(libs.map(l=>l.id)).size!==libs.length)throw Error('同一捕获同时选中了多个来源，请在本步保留一个输入。');
  return {project:S.project?.id,action,libraries:libs,reference:S.draft.reference,custom_reference:S.draft.custom_reference,params:{...S.draft.params}};
}
async function activateProject(p,preserve=false,draw=true){
  const seq=++S.projectSeq;save();const d=preserve?structuredClone(S.draft):null;let source=p;
  try {const got=await api(query('/api/project',{project:p.id}));source=got.project||got}catch{}
  if(seq!==S.projectSeq)return;
  resetPageState();S.project=source;S.jobs=[];S.preview=null;S.error='';S.files=[];S.dir='';S.scope='project';S.scopeLibrary='';S.fileFilter='';S.fileError='';++S.fileSeq;++nextQC;
  if(d){S.draft=d;save()}else restore(source.last_spec);
  try{localStorage.setItem('plant-sc-workbench.project',p.id)}catch{}
  await pollJobs(false);if(seq!==S.projectSeq||!draw)return;if(S.view==='panes')await loadDock();else if(S.view==='files')await loadFiles();else if(S.view==='plots')await loadPlots();else render();
}
async function pollJobs(draw=true){
  const pid=S.project?.id;if(!pid)return;
  try{const r=await api(query('/api/jobs',{project:pid}));if(pid!==S.project?.id)return;
    const previous=S.jobs.map(j=>(j.state||j.status)+j.id).join('|');
    S.jobs=Array.isArray(r)?r:r.jobs||[];
    if(draw&&S.view==='runs'){api('/api/queue').then(v=>{const el=q('#queueState');if(el)el.textContent='本机计算队列 · 并发上限 '+v.limit+' · 执行中 '+v.active+' · 等待 '+v.waiting}).catch(()=>{});const region=q('#jobsList');if(region&&S.jobs.length)region.innerHTML=S.jobs.map(j=>jobHTML(j)).join('');else if(!region)renderRuns()}
    if(draw&&isDockView())updateDockJobs(previous);
    if(draw&&S.view==='work'){
      const region=q('#lastJob');if(region)region.innerHTML=lastJobHTML();
      if(previous!==S.jobs.map(j=>j.state+j.id).join('|'))refreshStageJobs();
    }
  }catch(err){if(draw&&S.view==='runs')toast(err.message,true)}
}
async function pick(kind,process){
  try {const r=await api('/api/pick',{kind});if(r.path)await process(r.path)}
  catch(err){toast(err.message,true)}
}
function validateSpec(action){
  const libs=stageLibraries();
  if(!S.project)throw Error('请先创建或选择项目。');
  if(action==='build_reference'&&(!param('fasta','')||!param('gtf','')||!param('ref_name','plant_reference')))throw Error('请填写 FASTA、GTF 和参考名称。');
  if(['recluster','from_qc',...standalone].includes(action))return;
  if(action!=='build_reference'&&!libs.length)throw Error('请在本步输入中选择或上传文库。');
  if(action==='preview'&&libs.some(l=>l.kind==='fastq'))throw Error('该预览读取计数矩阵。FASTQ 可在运行页按完整流程定量并分析。');
  if(['read_qc','quantify'].includes(action)&&!libs.some(l=>l.kind==='fastq'))throw Error('此任务需要至少一个 FASTQ 文库。');
  if(action==='quantify'&&param('quantifier','starsolo')==='cellranger'&&!param('reference_dir',''))throw Error('请指定 Cell Ranger 参考索引目录。');
  if(action==='quantify'&&libs.filter(l=>l.kind==='fastq').some(l=>!String(l.prefix||'').trim()))throw Error('请在文库编辑器确认每个 FASTQ 文库的样本前缀。');
  if(['analysis','preview'].includes(action)&&S.draft.reference==='custom'&&!S.draft.custom_reference.trim())throw Error('请选择自定义参考基因集文件。');
}
function requireProject(callback){
  if(S.project)return callback();pendingAfterCreate=callback;showNewProject();q('#projErr').textContent='请先创建用于保存本次结果的项目。';
}
async function startJob(action){
  if(action==='single')action=activeModule();
  validateSpec(action);const pid=S.project.id;let spec=dataSpec(action,['from_qc','recluster','build_reference',...standalone].includes(action)?[]:stageLibraries());
  if(standalone.includes(action)){
    const src=moduleInput(),parent=q('#componentParent')?.value;
    if(src.mode==='file'?!src.file:!parent)throw Error('请为当前模块选择来源对象。');
    spec={project:pid,action,...(src.mode==='file'?{external_h5ad:src.file}:{parent_job:parent}),params:{...S.draft.params}};
  }
  if(action==='recluster'){const parent=q('#parentJob')?.value;if(!parent)throw Error('请选择成功完成的来源任务。'); spec={project:pid,action,parent_job:parent,params:{resolutions:param('resolutions',[0.5,1]),seed:param('seed',42)}}}
  if(action==='from_qc'){const parent=q('#qualityParent')?.value;if(!parent)throw Error('请选择成功完成的质控任务。');spec={project:pid,action,parent_job:parent,params:{...S.draft.params}}}
  if(['quantify','read_qc'].includes(action))spec.libraries=spec.libraries.filter(l=>l.kind==='fastq');
  if(action==='build_reference'){spec.libraries=[];spec.params.ref_name=param('ref_name','plant_reference')}
  const plan=await api('/api/recipe',spec);
  if(!plan.ready)throw Error(plan.blocks.flatMap(b=>b.issues).join('；'));
  const r=await api('/api/jobs',spec);if(pid!==S.project?.id)return;
  await pollJobs(false);if(pid!==S.project?.id)return;
  render();if(S.view==='work')setDockTab('right','jobs');toast('已提交任务 '+(r.id||r.job?.id||''));
}
async function previewQC(){
  validateSpec('preview');const pid=S.project.id,seq=++nextQC; const r=await api('/api/qc-preview',dataSpec('quality',stageLibraries(2)));
  if(seq!==nextQC||pid!==S.project?.id)return;S.preview=r.preview||r;render();toast('过滤预览已更新。');
}
function setParam(input){
  const key=input.dataset.param;if(!key)return;
  if(!input.checkValidity()){input.reportValidity();return}
  const raw=input.value.trim();let v=raw;
  if(raw===''){delete S.draft.params[key];markChanged();if(['fasta','gtf','whitelist','clusters_tsv','star_index','reference_dir','quantifier'].includes(key))persistInputs().catch(()=>{});return}
  switch(input.dataset.kind){
    case 'number':v=Number(raw);break;
    case 'boolean':v=raw==='true';break;
    case 'array':{
      v=raw.split(/[,，、;；\s]+/).filter(Boolean).map(Number);
      if(!v.length||v.length>16||v.some(n=>!Number.isFinite(n)||n<=0||n>100)){input.value=([param(key,[.5,1])].flat()).join(', ');throw Error('请输入 1 至 16 个大于 0 且不超过 100 的分辨率。')}v=Array.from(new Set(v));break
    }
  }
  S.draft.params[key]=v;markChanged();
  if(key==='quantifier')render();
  if(['fasta','gtf','whitelist','clusters_tsv','star_index','reference_dir','quantifier'].includes(key))persistInputs().catch(()=>{});
}
async function init(){
  const req=new URLSearchParams(location.search);
  const navigation=qa('.nav,#selectProject');
  navigation.forEach(button=>button.disabled=true);
  document.querySelectorAll('[data-icon]').forEach(el=>el.outerHTML=icon(el.dataset.icon));
  S.error='';try{
    const b=await api('/api/bootstrap');S.boot=b;S.projects=Array.isArray(b.projects)?b.projects:[];if(!b.references)S.boot.references=[];
    let prev;try{prev=localStorage.getItem('plant-sc-workbench.project')}catch{}
    const chosen=S.projects.find(p=>p.id===(req.get('project')||prev))||S.projects.find(p=>p.path===b.demo_project_path)||S.projects[0];
    if(chosen)await activateProject(chosen,false,false);else restore(null);
    readRoute(req);
    q('#serverDot').classList.add('ready');q('#serverStatus').textContent=b.read_only?'共享演示 · 只读':'本地计算服务已连接';
    if(b.read_only){
      const notice=document.createElement('p');notice.className='share-notice';notice.textContent='只读演示 · 可切换两个公开示例，浏览文件、报告和聚类图。运行自己的数据请使用本地工作台。';
      $main.before(notice);
    }
    if(S.view==='panes')await loadDock();else if(S.view==='files')await loadFiles();else if(S.view==='plots')await loadPlots();else render();
  }catch(err){S.error='连接本地服务失败。'+err.message;q('#serverStatus').textContent='服务连接失败';render()}
  navigation.forEach(button=>button.disabled=false);
  if(!S.boot.read_only)S.pollTimer=setInterval(()=>{if(!document.hidden)pollJobs()},3000);
}
function jobRetry(id){return api('/api/jobs/'+escId(id)+'/cancel',{})}
async function handle(act,el){
  const idx=Number(el.dataset.index);
  switch(act){
    case 'run-summary':await showScientificSummary(el.dataset.id);break;
    case 'view-embedding':openPlots(el.dataset.id,'umap');break;
    case 'view-plots':openPlots(el.dataset.id);break;
    case 'task-io':await showTaskIO(el.dataset.id);break;
    case 'inspect-recipe':await inspectRecipe();break;
    case 'export-recipe':exportRecipe();break;
    case 'import-recipe':importRecipe();break;
    case 'save-draft':await requireProject(async()=>{await api('/api/project-inputs',dataSpec('analysis',stageLibraries(5)));toast('项目方案已保存。')});break;
    case 'show-projects':showProjects();break;
    case 'new-project':showNewProject();break;
    case 'close':pendingAfterCreate=null;dlg.close();break;
    case 'activate-project':{const p=S.projects.find(v=>v.id===el.dataset.id);dlg.close();if(p){await activateProject(p);syncRoute()}break}
    case 'custom-pick':await requireProject(()=>{const ctx=stageContext('custom_reference');return pick('file',p=>useLocal(p,ctx))});break;
    case 'project-pick':await pick('directory',path=>{q('#newPath').value=path});break;
    case 'demo':await requireProject(async()=>{const ctx=stageContext(stageRoles[S.step]);const info=await api('/api/discover',{path:S.boot.demo_path});await bindStage(info,ctx)});break;
    case 'add-lib':libDialog();break;
    case 'edit-lib':libDialog(idx);break;
    case 'workflow-overview':workflowOverview();break;
    case 'guide-jump':dlg.close();go('work',idx);break;
    case 'go-step':go('work',idx);break;
    case 'runs':if(S.view==='work'){setDockTab('right','jobs');focusWorkDock('#tab-jobs')}else go('runs');break;
    case 'focus-stage-files':setDockTab('left','stage');focusWorkDock('#stageFilePanel');break;
    case 'expand-workspace':setWorkExpansion(!dock.expanded);break;
    case 'choose-upstream':stageBinding().handoffKind=el.dataset.kind;setDockTab('left','upstream');focusWorkDock('#tab-upstream');break;
    case 'use-output':await useHandoff(el);break;
    case 'focus-work-settings':setWorkExpansion(false);focusWorkDock('#workSettings');break;
    case 'files':if(S.view==='work'){setDockTab('left','files');focusWorkDock('#tab-files')}else go('files');break;
    case 'qc-preview':await requireProject(previewQC);break;
    case 'recluster':await requireProject(()=>startJob('recluster'));break;
    case 'open-output':S.scope='project';S.scopeLibrary='';openDir(el.dataset.path);focusWorkDock('#tab-files');break;
    case 'cancel-job':await jobRetry(el.dataset.id);await pollJobs();break;
    case 'refresh-jobs':await pollJobs();if(!isDockView())render();break;
    case 'refresh-files':await loadFiles();break;
    case 'open-dir':openDir(el.dataset.path);break;
    case 'open-file':if(isDockView())await openDockFile(el.dataset.path);else await openFile(el.dataset.path);break;
    case 'list':case 'gallery':S.fileMode=act;renderExplorer();break;
    case 'image-prev':stepImage(-1);break;
    case 'image-next':stepImage(1);break;
    case 'zoom-fit':S.zoom=0;applyZoom();break;
    case 'zoom-in':changeZoom(1.35);break;
    case 'zoom-out':changeZoom(1/1.35);break;
    default:if(act.startsWith('stage-')){await stageAction(act,el);break}if(await handleWorkspaceAction(act,el))break;if(act.startsWith('job-'))await requireProject(()=>startJob(act.slice(4)));
  }
}
document.addEventListener('click',async ev=>{
  const el=ev.target.closest('button');if(!el)return;
  if(el.id==='selectProject'){showProjects();return}
  if(el.id==='menuBtn'){q('#rail').classList.toggle('open');return}
  if(el.dataset.view){go(el.dataset.view);return}
  if(el.dataset.step!==undefined){go('work',Number(el.dataset.step));return}
  const act=el.dataset.act;if(!act||el.disabled)return;
  if(demoDisabled(act)){toast('共享演示仅供浏览。计算和文件操作可在本地工作台使用。');return}
  if(busyButtons.has(act))return;
  const long=['demo','qc-preview','recluster','activate-project','use-output'].includes(act)||act.startsWith('job-');
  if(long){el.disabled=true;el.setAttribute('aria-busy','true');busyButtons.add(act)}
  try {await handle(act,el)}catch(err){toast(err.message,true)}
  finally{if(long){el.disabled=false;el.removeAttribute('aria-busy');busyButtons.delete(act)}}
});
document.addEventListener('input',ev=>{
  const el=ev.target;
  if(el.id==='customReference'){S.draft.custom_reference=el.value;markChanged()}
  if(el.id==='fileFilter'){S.fileFilter=el.value;const r=q('#fileRows');if(r&&!S.loadingFiles&&!S.fileError)r.innerHTML=fileRows()}
});
document.addEventListener('change',async ev=>{
  const el=ev.target;try{
    if(el.dataset.param){setParam(el);return}
    if(el.id==='customReference')await persistInputs();
    if(el.id==='referenceSelect'){S.draft.reference=el.value;S.draft.referenceChosen=true;S.draft.referenceNote='';markChanged();await persistInputs();render()}
    if(el.id==='fileSource'){const val=el.value;if(val!=='project')await persistInputs();S.scope=val==='project'?'project':'input';S.scopeLibrary=S.scope==='input'?val.slice(6):'';openDir('')}
  }catch(err){toast(err.message,true)}
});
document.addEventListener('submit',async ev=>{
  const form=ev.target; if(!['projectForm','libForm'].includes(form.id))return;
  ev.preventDefault();const submit=q('[type="submit"]',form);if(submit.disabled)return;submit.disabled=true;
  try{
    if(form.id==='projectForm'){
      const preserve=!S.project, got=await api('/api/projects',{name:q('#newName').value.trim(),path:q('#newPath').value.trim()});const p=got.project||got;
      S.projects=[p,...S.projects.filter(x=>x.id!==p.id)];dlg.close();await activateProject(p,preserve);toast('项目已打开。');
      const after=pendingAfterCreate;pendingAfterCreate=null;if(after)await after();
    }else{
      const idx=Number(form.dataset.index),values=Object.fromEntries(Array.from(new FormData(form),([k,v])=>[k,v.trim()]));
      if(S.draft.libraries.some((l,i)=>i!==idx&&l.id===values.id))throw Error('捕获文库 ID 必须唯一。');
      if(/[\\/]/.test(values.id)||!values.id)throw Error('捕获文库 ID 不能为空或包含路径分隔符。');
      const old=idx>=0?S.draft.libraries[idx]:{};
      const next={...old,...values};
      if(idx<0){
        addStageLibraries({libraries:[next]},S.step);
      }else{
        S.draft.libraries[idx]=next;
        for(const binding of Object.values(S.draft.bindings||{}))if(binding.ids)binding.ids=binding.ids.map(id=>id===old.id?next.id:id);
      }
      markChanged();await persistInputs();dlg.close();render();
    }
  }catch(err){const out=q(form.id==='projectForm'?'#projErr':'#libErr');if(out)out.textContent=err.message;else toast(err.message,true)}
  finally{submit.disabled=false}
});
dlg.addEventListener('cancel',()=>{pendingAfterCreate=null});
document.addEventListener('keydown',ev=>{
  if(!dlg.open||S.modal!=='image'||['INPUT','SELECT','TEXTAREA'].includes(ev.target.tagName))return;
  if(ev.key==='ArrowLeft'){ev.preventDefault();stepImage(-1)}
  if(ev.key==='ArrowRight'){ev.preventDefault();stepImage(1)}
  if(ev.key==='+'||ev.key==='=')changeZoom(1.35);
  if(ev.key==='-')changeZoom(1/1.35);
});
init();

