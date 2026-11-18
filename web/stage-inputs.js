const stageRoles={1:'reads',2:'counts',5:'libraries'};
const stageModules={3:['features','pca'],4:['graph','umap','leiden'],5:standalone};
const inputHelp={reads:'10x 成对 FASTQ 或测序目录',counts:'10x MEX 目录、H5、整数计数 H5AD 或样本表',libraries:'10x FASTQ、计数矩阵或样本表',object:'带有所选模块必需字段的 H5AD'};
const fileFormats={reads:'.gz',counts:'.h5ad,.h5,.mtx,.gz,.tsv,.csv',libraries:'.h5ad,.h5,.mtx,.gz,.tsv,.csv',object:'.h5ad',fasta:'.fa,.fna,.fas,.fasta',gtf:'.gtf',custom_reference:'.json,.tsv',whitelist:'.txt,.tsv,.gz',clusters_tsv:'.tsv'};
let inputSaves=Promise.resolve();
function stageBinding(step=S.step){
  S.draft.bindings??={};
  return S.draft.bindings[step]??={};
}
function persistInputs(){
  save();
  const pid=S.project?.id;if(!pid||S.boot.read_only)return Promise.resolve();
  const {libraries,bindings,reference,custom_reference,referenceChosen}=S.draft;
  const aux=Object.fromEntries(Object.entries(S.draft.params).filter(([k])=>['fasta','gtf','whitelist','clusters_tsv','star_index','reference_dir','quantifier'].includes(k)));
  const settings=structuredClone({libraries,bindings:bindings||{},reference,custom_reference,referenceChosen,aux});
  const send=()=>api('/api/stage-settings',{project:pid,settings});
  inputSaves=inputSaves.catch(()=>{}).then(send);
  inputSaves.catch(err=>{if(S.project?.id===pid)toast('输入设置未保存：'+err.message,true)});
  return inputSaves;
}
function compatibleLibs(step=S.step){
  return S.draft.libraries.filter(l=>step===1?l.kind==='fastq':step===2?l.kind!=='fastq':true);
}
function stageLibraries(step=S.step){
  const selected=stageBinding(step).ids,libs=compatibleLibs(step);
  if(Array.isArray(selected))return libs.filter(l=>selected.includes(l.id));
  const preferred=new Map();
  for(const lib of libs)if(lib.upstream_capture)preferred.set(lib.upstream_capture,lib);
  return libs.filter(l=>{const chosen=preferred.get(l.upstream_capture||l.id);return !chosen||l===chosen});
}
function activeModule(step=S.step){
  const choices=stageModules[step]||standalone;
  const module=stageBinding(step).module;
  return choices.includes(module)?module:choices[0];
}
function moduleInput(){
  const binding=stageBinding();binding.objects??={};
  return binding.objects[activeModule()]??={mode:moduleParents(activeModule()).length?'parent':'file',file:'',parent:''};
}
function auxField(label,role){
  return '<div class="field full"><span>'+e(label)+'</span><div class="inline"><input class="inline-input" data-param="'+role+'" data-kind="text" aria-label="'+e(label)+'" value="'+e(param(role,''))+'">'+btn('选文件','stage-pick','file','','data-role="'+role+'"')+btn('上传','stage-upload','install','','data-role="'+role+'"')+'</div></div>';
}
function sourceButtons(role,folder=false){
  const attrs='data-role="'+role+'"';
  return '<div class="stage-buttons">'+btn('选择本机文件','stage-pick','file','',attrs)+
    (folder?btn('本机目录','stage-directory','folder','',attrs):'')+
    btn('上传文件','stage-upload','install','soft',attrs)+(folder?btn('上传文件夹','stage-upload-folder','folderOpen','',attrs):'')+'</div>';
}
function sourcePathForm(role){
  return '<details class="stage-path"><summary>输入本机路径</summary><div class="inline"><input class="inline-input" id="stagePath-'+role+'" aria-label="数据路径" placeholder="文件或目录的完整路径">'+btn('使用此路径','stage-path','arrow','','data-role="'+role+'"')+'</div></details>';
}
function captureInputs(){
  const step=S.step,role=stageRoles[step],libs=compatibleLibs(),sel=stageLibraries();
  const rows=libs.map(l=>{
    const i=S.draft.libraries.indexOf(l);
    return '<div class="stage-lib"><label><input type="checkbox" data-stage-lib="'+e(l.id)+'" '+(sel.includes(l)?'checked':'')+'><span><strong>'+e(l.id)+'</strong><small>'+e([kindLabels[l.kind]||l.kind,l.modality].filter(Boolean).join(' · '))+'</small></span></label>'+textBtn('编辑','edit-lib','data-index="'+i+'"')+'</div>';
  }).join('');
  const qjobs=step===2?S.jobs.filter(j=>j.state==='succeeded'&&(j.action==='quantify'||j.has_reads)):[];
  const upstream=qjobs.length?'<div class="stage-upstream"><label class="field">从定量结果接入<select id="quantSource">'+options(qjobs.map(j=>[j.id,dateStr(j.created)+' · '+j.id]),stageBinding().quantJob||qjobs[0].id)+'</select></label>'+btn('使用定量矩阵','stage-quant','link')+'</div>':'';
  const sample=step!==1&&S.boot.demo_path?textBtn('使用示例矩阵','demo'):'';
  let form='<p class="stage-help">'+e(inputHelp[role])+'</p>'+sourceButtons(role,true)+btn('从上游输出选择','choose-upstream','link','stage-source-link','data-kind="counts"')+sourcePathForm(role)+upstream+
    (rows?'<div class="stage-selection"><span>本步使用 '+sel.length+' / '+libs.length+' 个文库</span>'+rows+'</div>':'')+
    '<div class="actions">'+textBtn('手动登记文库','add-lib')+sample+'</div>'+
    '<details class="accordion"><summary>物种与参考基因集 · '+e(displayRef(refOf())||'未指定')+'</summary><div class="fields">'+coreFields()+'</div></details>';
  return card(step===1?'测序输入':step===2?'质控输入':'全流程输入','folderOpen',form,'','stage-input');
}
function methodPanel(){
  const step=S.step,module=activeModule(),src=moduleInput(),parents=moduleParents(module);
  const parent=parents.some(j=>j.id===src.parent)?src.parent:parents[0]?.id;
  const choice='<label class="field">执行模块<select id="singleModule">'+options(stageModules[step].map(k=>[k,jobNames[k]]),module)+'</select></label>';
  const mode='<label class="field">输入来源<select id="stageMode">'+options([['parent','本项目上游任务'],['file','本机或上传的 H5AD']],src.mode)+'</select></label>';
  const rule={features:'已清洗的整数计数，来自 layers/counts 或 X',pca:'对数表达 X 和 var/highly_variable',graph:'主成分 obsm/X_pca 或 X_pca_harmony',umap:'Scanpy 近邻图及距离、neighbors 元数据',leiden:'细胞之间的连通权重矩阵 obsp/connectivities'}[module];
  const picker=src.mode==='file'?sourceButtons('object')+sourcePathForm('object')+(src.file?'<div class="stage-bound"><strong>'+e(lastName(src.file))+'</strong><small>'+e(src.file)+'</small></div>':''):
    (parents.length?'<label class="field">来源任务<select id="componentParent">'+options(parents.map(j=>[j.id,jobNames[j.action]+' · '+dateStr(j.created)+' · '+j.id.slice(0,8)]),parent)+'</select></label>':'<p class="hint">本项目尚无符合条件的上游任务，可选择 H5AD。</p>');
  return card(step===5?'单独运行模块':step===3?'降维输入':'聚类输入','layers',
    '<div class="fields">'+choice+mode+'</div><p class="module-explanation">'+e(moduleGuidance[module])+'</p><p class="stage-help">所需输入 · '+e(rule)+'</p>'+picker+btn('从上游输出选择','choose-upstream','link','stage-source-link','data-kind="module"')+
    '<div class="actions">'+btn('运行'+jobNames[module],'job-single','play','primary',(src.mode==='file'?src.file:parent)?'':'disabled')+'</div>','','stage-input');
}
function addStageLibraries(info,step){
  const selected=new Set(stageLibraries(step).map(l=>l.id));
  // The full workflow inherits the inventory until the researcher makes a selection.
  for(const other of [1,2]){
    const binding=stageBinding(other);
    if(other!==step&&!Array.isArray(binding.ids))binding.ids=compatibleLibs(other).map(l=>l.id);
  }
  for(const row of info.libraries){
    let lib=S.draft.libraries.find(l=>l.path===row.path&&(l.prefix||'')===(row.prefix||''));
    if(lib&&row.upstream_job)Object.assign(lib,{upstream_job:row.upstream_job,upstream_capture:row.upstream_capture});
    if(!lib){
      lib={...row};const base=lib.id;let n=2;
      while(S.draft.libraries.some(l=>l.id===lib.id))lib.id=base+'-'+n++;
      S.draft.libraries.push(lib);
    }
    if(lib.upstream_capture)for(const other of S.draft.libraries){
      if(other!==lib&&(other.upstream_capture||other.id)===lib.upstream_capture)selected.delete(other.id);
    }
    selected.add(lib.id);
  }
  stageBinding(step).ids=[...selected];
  if(S.draft.reference==='none'&&!S.draft.referenceChosen&&info.recommended_reference){
    S.draft.reference=info.recommended_reference;S.draft.referenceNote=info.recommendation?.reason||'';
  }
}
function stageContext(role){
  return {role,project:S.project?.id,step:S.step,module:stageModules[S.step]?activeModule():undefined,params:{...S.draft.params}};
}
async function bindStage(info,context){
  if(S.project?.id!==context.project)return;
  if(info.libraries)addStageLibraries(info,context.step);
  else if(context.role==='object'){
    const binding=stageBinding(context.step);binding.objects??={};
    binding.objects[context.module]={...binding.objects[context.module],file:info.path,mode:'file'};
  }else if(context.role==='custom_reference'){
    S.draft.reference='custom';S.draft.custom_reference=info.path;S.draft.referenceChosen=true;
  }else S.draft.params[context.role]=info.path;
  markChanged();await persistInputs();
  if(S.project?.id===context.project&&S.step===context.step&&S.view==='work'){render();toast(info.libraries?'已加入本步输入 · '+info.libraries.length+' 个文库':'已绑定 '+lastName(info.path))}
}
async function useLocal(path,context){
  if(!path?.trim())throw Error('请提供本机文件或目录路径');
  const info=await api('/api/stage-source',{...context,path:path.trim()});
  await bindStage(info,context);
}
function selectUpload(context,directory){
  const input=document.createElement('input');input.type='file';
  if(directory)input.webkitdirectory=true;else{input.accept=fileFormats[context.role]||'';input.multiple=['reads','counts','libraries'].includes(context.role)}
  input.onchange=async()=>{
    if(!input.files.length||context.project!==S.project?.id)return;
    const files=Array.from(input.files);
    const meta=new TextEncoder().encode(JSON.stringify({params:context.params,files:files.map(f=>({name:f.webkitRelativePath||f.name,size:f.size}))}));
    const prefix=new DataView(new ArrayBuffer(4));prefix.setUint32(0,meta.length);
    const body=new Blob([prefix,meta,...files],{type:'application/octet-stream'});
    try{
      toast('正在导入 '+files.length+' 个文件…');
      const args={project:context.project,role:context.role,module:context.module};
      const response=await fetch(query('/api/stage-upload',args),{method:'POST',body});
      const info=await response.json();if(!response.ok)throw Error(info.error||'文件导入失败');
      await bindStage(info,context);
    }catch(err){toast(err.message,true)}
  };input.click();
}
async function reuseQuant(job=q('#quantSource')?.value,capture=''){
  const ctx=stageContext('counts');
  const data=await getHandoffArchive(ctx.project,job);
  if(ctx.project!==S.project?.id||ctx.step!==S.step)return;
  const libs=data.artifacts.filter(a=>a.target==='counts'&&(!capture||a.capture===capture)).map(a=>a.lib);
  if(!libs.length)throw Error('所选任务缺少该捕获的定量矩阵。');
  stageBinding(ctx.step).quantJob=job;
  await bindStage({libraries:libs,recommended_reference:refOf(data.reference)?data.reference:undefined},ctx);
}
function stageAction(act,el){
  const role=el.dataset.role,ctx=stageContext(role);
  if(act==='stage-upload'||act==='stage-upload-folder')return requireProject(()=>selectUpload(stageContext(role),act.endsWith('folder')));
  if(act==='stage-pick'||act==='stage-directory')return requireProject(()=>{const selected=stageContext(role);return pick(act==='stage-pick'?'file':'directory',path=>useLocal(path,selected))});
  if(act==='stage-path')return requireProject(()=>useLocal(el.parentElement.querySelector('input').value,ctx.project?ctx:stageContext(role)));
  if(act==='stage-quant')return reuseQuant();
}
document.addEventListener('change',ev=>{
  const el=ev.target;
  if(el.hasAttribute('data-stage-lib')){
    const ids=new Set(stageLibraries().map(l=>l.id));if(el.checked)ids.add(el.dataset.stageLib);else ids.delete(el.dataset.stageLib);
    stageBinding().ids=[...ids];markChanged();persistInputs().catch(()=>{});render();
  }else if(el.id==='qualityParent'||el.id==='parentJob'){
    stageBinding()[el.id]=el.value;persistInputs().catch(()=>{});renderStageInputsRail();
  }else if(el.id==='singleModule'||el.id==='stageMode'||el.id==='componentParent'){
    if(el.id==='singleModule'){stageBinding().module=el.value;stageBinding().handoffKind='module'}
    else if(el.id==='stageMode')moduleInput().mode=el.value;
    else moduleInput().parent=el.value;
    persistInputs().catch(()=>{});render();
  }
});

