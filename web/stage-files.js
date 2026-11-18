const stageOutputs={1:['quantify','read_qc','build_reference'],2:['quality','analysis'],3:['pca','features','from_qc','analysis'],4:['graph','umap','leiden','recluster','from_qc','analysis']};
let stageRequest=0;
function stageMatchesJob(j){
  const allowed=stageOutputs[S.step];
  return !allowed||allowed.includes(j.action)||(S.step===1&&j.action==='analysis'&&j.has_reads);
}
function outputJobs(){return S.jobs.filter(j=>j.state==='succeeded'&&stageMatchesJob(j))}
function stageInputsHTML(){
  const row=(label,detail,key)=>'<div class="context-file">'+icon('file')+'<div>'+(key?'<button class="text-btn" data-input-folder="'+e(key)+'" title="在文件分区查看">'+e(label)+'</button>':'<strong>'+e(label)+'</strong>')+'<small title="'+e(detail)+'">'+e(detail)+'</small></div></div>';
  let rows=[];
  if(stageRoles[S.step])rows=stageLibraries().map(l=>{
    const members=l.input_files||[];
    if(!members.length)return row(lastName(l.path),l.id+' · '+l.path,l.id);
    return row(l.id+' · '+(kindLabels[l.kind]||'文库'),members.slice(0,3).join(' · ')+(members.length>3?' 等 '+members.length+' 个文件':''),l.id);
  });
  if(stageModules[S.step]){
    const src=moduleInput();
    if(src.mode==='file'&&src.file)rows.push(row(lastName(src.file),src.file,objectKey(S.step,activeModule())));
    if(src.mode==='parent'){
      const parent=q('#componentParent')?.value||src.parent||moduleParents(activeModule())[0]?.id;
      if(parent){
        const job=S.jobs.find(j=>j.id===parent);
        const filename=job?.action==='quality'?'qc.h5ad':standalone.includes(job?.action)?'component.h5ad':'analysis.h5ad';
        const dir='runs/'+parent+'/results';
        rows.push('<div class="context-file">'+icon('file')+'<div><button class="text-btn" data-stage-folder="'+e(dir)+'" data-job="'+e(parent)+'">'+e(filename)+'</button><small>'+e((jobNames[job?.action]||'上游任务')+' · '+parent)+'</small></div></div>');
      }
    }
  }
  if(S.step===1)for(const key of ['fasta','gtf','star_index','reference_dir','whitelist']){
    const path=S.draft.params[key];if(path)rows.push(row(lastName(path),path));
  }
  if(S.step===2&&S.draft.params.clusters_tsv)rows.push(row(lastName(S.draft.params.clusters_tsv),S.draft.params.clusters_tsv));
  if(S.draft.reference==='custom'&&S.draft.custom_reference&&stageRoles[S.step])rows.push(row(lastName(S.draft.custom_reference),S.draft.custom_reference));
  return rows.join('')||'<p class="hint">选择输入后在此显示。</p>';
}
function renderStageInputsRail(){const el=q('#stageInputList');if(el)el.innerHTML=stageInputsHTML()}
function stageFilesPanel(){
  return '<aside id="stageFilePanel" tabindex="-1" class="aside stage-rail">'+card('本步文件','files','<h3 class="context-label">当前输入</h3><div id="stageInputList"></div><div class="rule"></div><h3 class="context-label">已生成的结果</h3><div id="stageJobPicker"></div><div id="stageOutputList"></div>')+
    card('本步最近任务','history','<div id="lastJob">'+lastJobHTML()+'</div>',textBtn('全部','runs'))+'</aside>';
}
function refreshStageJobs(){
  if(S.view!=='work')return;
  renderStageInputsRail();refreshStageFiles();
  for(const [id,actions] of [['componentParent',stageModules[S.step]?moduleParents(activeModule()):[]],['qualityParent',S.jobs.filter(j=>j.state==='succeeded'&&j.action==='quality')]]){
    const select=q('#'+id);if(select&&document.activeElement!==select&&actions.length){
      const value=select.value;select.innerHTML=options(actions.map(j=>[j.id,(jobNames[j.action]||j.action)+' · '+dateStr(j.created)+' · '+j.id.slice(0,8)]),value);
    }
  }
}
async function refreshStageFiles(){
  const pid=S.project?.id,step=S.step;
  const list=q('#stageOutputList'),picker=q('#stageJobPicker');
  if(!list||!picker)return;
  renderStageInputsRail();
  const jobs=outputJobs(),selected=stageBinding().output,job=jobs.find(j=>j.id===selected)||jobs[0];
  if(!job){++stageRequest;delete list.dataset.source;list.innerHTML='<p class="hint">此工作位尚无已完成的结果。</p>';picker.innerHTML='';return}
  picker.innerHTML='<select aria-label="本步结果来源" id="stageOutputJob" class="inline-input">'+options(jobs.map(j=>[j.id,(jobNames[j.action]||j.action)+' · '+dateStr(j.created)+' · '+j.id.slice(0,8)]),job.id)+'</select>';
  if(list.dataset.source===job.id)return;
  const seq=++stageRequest;list.dataset.source=job.id;
  list.innerHTML='<p class="hint">读取结果文件…</p>';
  try{
    const data=await api(query('/api/stage-files',{project:pid,job:job.id,step}));
    if(!list.isConnected||seq!==stageRequest||pid!==S.project?.id)return;
    const renderRow=f=>'<div class="stage-result-row"><button type="button" class="context-result" data-stage-artifact="'+e(f.path)+'" data-kind="'+e(f.type)+'" title="'+e(f.path)+'">'+icon(f.type==='dir'?'folder':entryType(f)==='image'?'picture':entryType(f)==='table'?'table':'file')+'<span>'+e(f.name)+(f.selectors?.length?'<small>'+e(f.selectors.join(' · '))+'</small>':'')+'</span>'+icon('right')+'</button>'+fileHandoffAction(f.path,'project')+'</div>';
    list.innerHTML=(data.items.length?data.items.slice(0,6).map(renderRow).join(''):'<p class="hint">从来源目录查看该任务的归档文件。</p>')+
      (data.items.length>6?'<details class="accordion"><summary>其余 '+(data.items.length-6)+' 项</summary>'+data.items.slice(6).map(renderRow).join('')+'</details>':'')+
      '<button type="button" class="text-btn" data-stage-folder="'+e(data.directory)+'" data-job="'+e(job.id)+'">'+icon('folderOpen')+' 在分区查看此目录</button>';
  }catch(err){if(list.isConnected&&seq===stageRequest){delete list.dataset.source;list.innerHTML=banner(err.message,true)}}
}
function openStageFolder(path,job){
  S.scope='project';S.scopeLibrary='';openDir(path);
  if(job)openPlots(job);
  focusWorkDock('#tab-files');
}
document.addEventListener('click',ev=>{
  const button=ev.target.closest('button');if(!button)return;
  if(button.dataset.inputFolder){
    S.scope='input';S.scopeLibrary=button.dataset.inputFolder;openDir('');focusWorkDock('#tab-files');
  }else if(button.dataset.stageArtifact){
    if(button.dataset.kind==='dir'){openStageFolder(button.dataset.stageArtifact,q('#stageOutputJob').value);return}
    openDockFile(button.dataset.stageArtifact,'project','');focusWorkDock('#tab-preview');
  }else if(button.dataset.stageFolder)openStageFolder(button.dataset.stageFolder,button.dataset.job);
});
document.addEventListener('change',ev=>{
  if(ev.target.id==='stageOutputJob'){stageBinding().output=ev.target.value;persistInputs().catch(()=>{});refreshStageFiles()}
});

