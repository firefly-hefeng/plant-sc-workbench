function fileArgs(path){return {project:S.project?.id,path,scope:S.scope,library:S.scope==='input'?S.scopeLibrary:undefined}}
function fileURL(path,download=false){return query('/api/file',{...fileArgs(path),download:download?'1':undefined})}
function folderEntries(){const name=S.fileFilter.trim().toLowerCase();return S.files.filter(f=>!name||String(f.name).toLowerCase().includes(name))}
function fileRows(){
  const entries=sortEntries(folderEntries());if(!entries.length)return empty('folderOpen',S.fileFilter?'没有匹配的文件':'目录为空',S.fileFilter?'可更换搜索词。':'完成的分析会将结果写入各自的任务目录。');
  if(S.fileMode==='gallery'){
    const dirs=entries.filter(f=>entryType(f)==='dir'),imgs=entries.filter(f=>entryType(f)==='image');
    return '<div class="pad">'+(dirs.length?'<div class="inline">'+dirs.map(f=>btn(f.name,'open-dir','folder','','data-path="'+e(f.path)+'"')).join('')+'</div><div class="rule"></div>':'')+(imgs.length?'<div class="gallery">'+imgs.map(f=>'<button class="thumb" data-act="open-file" data-path="'+e(f.path)+'"><img loading="lazy" alt="" src="'+e(fileURL(f.path))+'"><span>'+e(f.name)+'</span></button>').join('')+'</div>':empty('picture','当前目录没有图片','进入包含绘图结果的目录，或切换到列表查看全部文件。'))+'</div>';
  }
  return '<div class="scroll"><table class="table"><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>修改时间</th><th aria-label="操作"></th></tr></thead><tbody>'+entries.map(f=>{
    const kind=entryType(f),ic={dir:'folder',image:'picture',table:'table',report:'report'}[kind]||'file';
    return '<tr><td class="file-cell"><button class="file-name" data-act="'+(kind==='dir'?'open-dir':'open-file')+'" data-path="'+e(f.path)+'">'+icon(ic)+e(f.name)+'</button></td><td class="minor">'+previewTypes[kind]+'</td><td class="minor nowrap">'+(kind==='dir'?'—':e(humanSize(f.size)))+'</td><td class="minor nowrap">'+e(dateStr(f.mtime||f.modified))+'</td><td>'+fileHandoffAction(f.path,S.scope)+(kind==='dir'?'':btn('复制','copy-entry','','','data-path="'+e(f.path)+'"'))+'</td></tr>';
  }).join('')+'</tbody></table></div>';
}
function objectKey(step,module){return '/object/'+step+'/'+module}
function fileSources(){
  const sources=[['project','项目工作目录'],...S.draft.libraries.filter(l=>l.id).map(l=>['input:'+l.id,'输入 · '+l.id])];
  for(const [step,binding] of Object.entries(S.draft.bindings||{}))for(const [module,source] of Object.entries(binding.objects||{})){
    if(source.file)sources.push(['input:'+objectKey(step,module),steps[step][0]+' · '+jobNames[module]+' · '+lastName(source.file)]);
  }
  return sources;
}
async function loadFiles(){
  if(S.view==='files')renderNav();
  const seq=++S.fileSeq;S.fileError='';S.loadingFiles=true;renderExplorer();
  if(!S.project){S.files=[];S.loadingFiles=false;renderExplorer();return}
  try {const r=await api(query('/api/files',fileArgs(S.dir)));
    if(seq!==S.fileSeq)return;
    const entries=Array.isArray(r)?r:r.entries||r.files||[];
    S.files=entries.map(f=>({...f,path:folderPath(f.path||[S.dir,f.name].filter(Boolean).join('/'))})).sort((a,b)=>Number(entryType(b)==='dir')-Number(entryType(a)==='dir')||String(a.name).localeCompare(String(b.name),'zh-CN',{numeric:true}));
    S.dir=folderPath(r.path??S.dir);S.dirAbsolute=r.absolute||'';
    rememberTree(S.dir,S.files);
  }catch(err){if(seq!==S.fileSeq)return;S.files=[];S.fileError=err.message}
  finally{if(seq===S.fileSeq){S.loadingFiles=false;if(isDockView()||S.view==='files')renderExplorer()}}
}
function openDir(path){
  S.dir=folderPath(path);S.fileFilter='';if(isDockView())setDockTab('left','files',false);else S.view='files';syncRoute();loadFiles();
}
function modalShow(title,content,mode,wide=false){
  if(dlg.open)dlg.close();S.modal=mode;
  dlg.className=wide?'wide':'';
  modal.innerHTML='<div class="dialog-top"><h2 id="dialogTitle">'+e(title)+'</h2><button type="button" class="icon-btn" data-act="close" aria-label="关闭">'+icon('x')+'</button></div><div class="dialog-content">'+content+'</div>';
  dlg.setAttribute('aria-labelledby','dialogTitle');dlg.showModal();
}
function imageList(args){
  const current=fileArgs('');
  if(args&&((args.scope||'project')!==(current.scope||'project')||(args.library||'')!==(current.library||'')))return [];
  return S.files.filter(f=>entryType(f)==='image');
}
function showImage(f,keepZoom=false,args=fileArgs(f.path)){
  S.viewFile=f;S.viewImageArgs=args;if(!keepZoom)S.zoom=0;const list=imageList(args);const i=list.findIndex(it=>it.path===f.path);
  const b='<div class="viewer-tools"><div class="inline">'+btn('上一张','image-prev','','',i<=0?'disabled':'')+btn('下一张','image-next','','',i<0||i>=list.length-1?'disabled':'')+'<span class="minor">'+(i>=0?(i+1)+' / '+list.length:'')+'</span></div><div class="inline">'+btn('−','zoom-out')+'<output id="zoomValue"></output>'+btn('＋','zoom-in')+btn('适应窗口','zoom-fit')+'<a class="btn" download href="'+e(query('/api/file',{...args,download:1}))+'">'+icon('install')+'下载</a></div></div><div class="viewer-wrap fit" id="imageStage"><img id="viewImage" alt="'+e(f.name)+'" src="'+e(query('/api/file',args))+'"></div>';
  modalShow(f.name,b,'image',true); q('#viewImage').addEventListener('load',applyZoom);applyZoom();
}
function applyZoom(){const img=q('#viewImage'),stage=q('#imageStage');if(!img||!stage)return;
  stage.classList.toggle('fit',S.zoom===0);
  if(S.zoom===0){img.style.width='';img.style.height='';q('#zoomValue').textContent='适应'}
  else{img.style.width=Math.max(1,Math.round((img.naturalWidth||stage.clientWidth)*S.zoom))+'px';img.style.height='auto';q('#zoomValue').textContent=Math.round(S.zoom*100)+'%'}
}
function changeZoom(factor){const img=q('#viewImage'),stage=q('#imageStage');if(!img||!stage)return;const current=S.zoom||Math.min(stage.clientWidth/(img.naturalWidth||stage.clientWidth),stage.clientHeight/(img.naturalHeight||stage.clientHeight));S.zoom=Math.max(0.05,Math.min(12,current*factor));applyZoom()}
async function openFile(path,args=fileArgs(path),fragment=''){
  const name=lastName(path),f=S.files.find(it=>it.path===path);
  if(entryType({name})==='image'){showImage(f||{name,path},false,args);return}
  const download='<a class="btn" download href="'+e(query('/api/file',{...args,download:1}))+'">'+icon('install')+'下载原文件</a>';
  modalShow(name,'<div class="file-reader"></div><div class="actions">'+download+'</div>','file',true);
  await readPreview(q('.file-reader',dlg),args,(next,hash)=>openFile(next,{...args,path:next},hash),fragment);
}
function stepImage(delta){const list=imageList(S.viewImageArgs);const i=list.findIndex(it=>it.path===S.viewFile?.path);if(i>=0&&list[i+delta])showImage(list[i+delta],true)}
function showProjects(){const rows=S.projects.map(p=>'<button class="dir-select" type="button" data-act="activate-project" data-id="'+e(p.id)+'"><strong>'+e(p.name)+'</strong><br><span class="hint mono">'+e(p.path||p.root||'')+'</span></button>').join('');
  modalShow('选择项目','<div class="dialog-list">'+(rows||empty('folder','还没有项目','新建项目目录，输入数据可保留原位。'))+'</div><div class="actions">'+btn('新建项目','new-project','plus','primary')+'</div>','projects');
}
function showNewProject(){modalShow('新建分析项目','<form id="projectForm"><div class="fields"><label class="field full">项目名称<input id="newName" required maxlength="90" placeholder="例如 拟南芥根尖单核分析"></label><label class="field full"><span>工作目录（可选）</span><div class="inline"><input id="newPath" class="inline-input" placeholder="留空将由工作台分配独立目录">'+btn('浏览','project-pick','folder')+'</div><span class="hint">任务结果保存在此，不需要复制原始数据。</span></label></div><p id="projErr" class="block-error"></p><div class="actions">'+btn('取消','close')+'<button class="btn primary" type="submit">创建项目</button></div></form>','new-project');q('#newName').focus()}
function libDialog(index=-1){
  const l=index>=0?S.draft.libraries[index]:{id:'',sample:'',path:'',kind:S.step===1?'fastq':'matrix',modality:'scRNA'};
  const input=(key,label,v,opts={})=>'<label class="field '+(opts.full?'full':'')+'"><span>'+e(label)+'</span><input name="'+e(key)+'" value="'+e(v)+'" '+(opts.required?'required':'')+' placeholder="'+e(opts.hint||'')+'"></label>';
  const select=(key,label,items,v)=>'<label class="field"><span>'+e(label)+'</span><select name="'+e(key)+'">'+options(items,v)+'</select></label>';
  const types=[['matrix','计数矩阵（10x 或 H5AD）'],['raw','原始液滴矩阵'],['fastq','FASTQ 文库']];
  modalShow(index>=0?'编辑文库':'添加文库','<form id="libForm" data-index="'+index+'"><div class="fields">'+
    input('id','捕获文库 ID',l.id,{required:true})+input('sample','独立生物样本',l.sample,{required:true})+
    select('kind','数据类型',types.filter(([k])=>S.step===1?k==='fastq':S.step===2?k!=='fastq':true),['fastq','raw'].includes(l.kind)?l.kind:'matrix')+select('modality','实验模态',[['scRNA','单细胞 scRNA'],['snRNA','单核 snRNA']],l.modality||'scRNA')+
    input('path','输入路径',l.path,{full:true,required:true})+input('batch','批次',l.batch)+input('condition','处理条件',l.condition)+
    '</div><details class="accordion" '+(l.kind==='fastq'||l.kind==='raw'?'open':'')+'><summary>文件与读段 设置</summary><div class="fields">'+
    input('prefix','FASTQ 样本前缀',l.prefix,{hint:'与 FASTQ 文件名匹配'})+input('counts_layer','H5AD 计数层',l.counts_layer,{hint:'留空使用既定入口规则'})+
    input('filtered_path','与 raw 匹配的过滤矩阵路径',l.filtered_path,{full:true})+input('raw_path','配套原始液滴矩阵路径',l.raw_path,{full:true})+input('corrected_path','配套环境 RNA 校正矩阵路径',l.corrected_path,{full:true})+input('clusters_tsv','SoupX 粗聚类 TSV 路径',l.clusters_tsv,{full:true})+'</div></details><p id="libErr" class="block-error"></p><div class="actions">'+btn('取消','close')+'<button class="btn primary" type="submit">保存文库</button></div></form>','library');q('[name="id"]',dlg).focus()
}

