"use strict";

const glyphs = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  folder:'<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  history:'<path d="M3 11a9 9 0 1 1 2 7m-2-6V7m0 5h5m4-5v5l3 2"/>',
  down:'<path d="m7 10 5 5 5-5"/>',right:'<path d="m9 6 6 6-6 6"/>',up:'<path d="m6 14 6-6 6 6"/>',
  layers:'<path d="m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  menu:'<path d="M3 5h18M3 12h18M3 19h18"/>',plus:'<path d="M12 5v14M5 12h14"/>',
  folderOpen:'<path d="M3 9V5h7l2 3h8v2M3 10h19l-4 10H3z"/>',
  files:'<path d="M7 3h9l4 4v14H7zM16 3v5h5M4 6v14"/>',
  check:'<path d="m4 12 5 5L20 6"/>',x:'<path d="m6 6 12 12M18 6 6 18"/>',
  sliders:'<path d="M4 5h5m4 0h7M4 12h10m4 0h2M4 19h3m4 0h9"/><circle cx="11" cy="5" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="9" cy="19" r="2"/>',
  leaf:'<path d="M3 19C3 8 11 4 21 3c0 11-6 17-13 17m-5 2L16 9"/>',
  play:'<path d="m8 5 11 7-11 7z"/>',install:'<path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5"/>',
  picture:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="1.5"/><path d="m4 18 5-5 3 3 4-6 5 7"/>',
  table:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
  file:'<path d="M5 3h9l5 5v13H5zM14 3v6h5"/>',
  zoom:'<circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6M7 10h6m-3-3v6"/>',
  report:'<path d="M5 4h14v16H5zM8 15l3-4 2 2 3-5"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  refresh:'<path d="M20 10a8 8 0 1 0-1 7M20 4v6h-6"/>',
  link:'<path d="m8 16 8-8m-5-1 2-2a5 5 0 0 1 7 7l-2 2m-5 3-2 2a5 5 0 0 1-7-7l2-2"/>',
  compare:'<path d="M4 5h16M4 19h16m-7-14 3 3-3 3m-2 2-3 3 3 3"/>',
  database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>'
};
const icon = k => '<svg aria-hidden="true" class="ico" viewBox="0 0 24 24">'+(glyphs[k]||glyphs.file)+'</svg>';
const e = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const escId = v => encodeURIComponent(String(v));
const q = (s,root=document)=>root.querySelector(s);
const qa = (s,root=document)=>Array.from(root.querySelectorAll(s));
const nfmt = v => typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('zh-CN') : String(v ?? '—');
const steps = [
  null,
  ['测序与定量','检查成对读段质量，按捕获使用 STARsolo 或 Cell Ranger 定量。','database'],
  ['质控与清洗','按捕获查看过滤影响，保留植物细胞或细胞核的质量判定依据。','sliders'],
  ['降维与批次诊断','选择高变基因与主成分，并决定是否比较批次校正表示。','layers'],
  ['聚类与比较','设置邻居图与 Leiden 分辨率，在同一图上比较不同分区。','compare'],
  ['运行与交付','检查当前方案，运行分析并在文件管理器查看图、表和 H5AD。','report']
];
const jobLabels = {queued:'等待运行',running:'正在运行',succeeded:'已完成',failed:'失败',cancelled:'已取消',interrupted:'中断'};
const kindLabels = {matrix:'计数矩阵',filtered:'过滤矩阵',h5ad:'H5AD',raw:'原始液滴',fastq:'FASTQ'};
const baseState = ()=>({libraries:[], reference:'none', custom_reference:'', params:{}});
const S = {view:'work',step:2,boot:{},projects:[],project:null,draft:baseState(),jobs:[],preview:null,files:[],dir:'',scope:'project',scopeLibrary:'',fileFilter:'',fileMode:'list',fileError:'',loadingFiles:false,fileSeq:0,projectSeq:0,error:'',busy:false,modal:'',viewFile:null,zoom:0,pollTimer:null,pickUntil:0};
const $main = q('#content'), dlg=q('#dialog'), modal=q('#dialogBody');
const cacheKey = ()=>'plant-sc-workbench.draft.v2.'+(S.project?.id || 'unsaved');
function save(){ try {sessionStorage.setItem(cacheKey(),JSON.stringify(S.draft))} catch{} }
function restore(defaultSpec){
  let obj=defaultSpec || {};
  try { const t=sessionStorage.getItem(cacheKey()); if(t)obj=JSON.parse(t); } catch{}
  obj={...obj,...(S.project?.stage_inputs||{}),params:{...(obj.params||{}),...(S.project?.stage_inputs?.aux||{})}};
  S.draft={...baseState(),...obj,libraries:Array.isArray(obj.libraries)?obj.libraries:[],params:{...(obj.params||{})}};
  if(typeof S.draft.reference!=='string')S.draft.reference='none';
}
function toast(msg,bad=false){const el=q('#toast');el.textContent=msg;el.className='toast show'+(bad?' err':'');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),bad?8500:3800)}
async function api(path,data,signal){
  const opt={method:data===undefined?'GET':'POST',signal,headers:{'Accept':'application/json'}};
  if(data!==undefined){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(data)}
  const res=await fetch(path,opt);
  let val;try {val=await res.json()}catch{throw Error('服务返回了不可识别的响应（'+res.status+'）。')}
  if(!res.ok || val?.ok===false){const detail=val?.error?.message??val?.error??val?.detail??val?.message;throw Error(typeof detail==='string'?detail:'请求失败（'+res.status+'）。')}
  return val;
}
function query(path,obj){const qp=new URLSearchParams();for(const [k,v] of Object.entries(obj))if(v!==undefined&&v!==null&&v!=='')qp.set(k,v);return path+'?'+qp.toString()}
function card(title,ic,body,end='',cls=''){return '<section class="card '+cls+'"><div class="cap"><h2>'+icon(ic)+e(title)+'</h2>'+end+'</div><div class="pad">'+body+'</div></section>'}
function empty(ic,title,description){return '<div class="empty">'+icon(ic)+'<strong>'+e(title)+'</strong>'+e(description)+'</div>'}
function demoDisabled(act){
  return S.boot.read_only&&(/^(job-|stage-(upload|local|directory|path|choose)|custom-pick|project-pick)/.test(act)||
    ['qc-preview','recluster','new-project','add-lib','edit-lib','demo','save-draft','use-output','mkdir-dialog','copy-entry','reveal-dir','inspect-recipe'].includes(act));
}
function btn(label,act,ic='',style='',attrs=''){if(demoDisabled(act))attrs+=' disabled title="计算和文件操作可在本地工作台使用"';return '<button type="button" class="btn '+style+'" data-act="'+act+'" '+attrs+'>'+(ic?icon(ic):'')+e(label)+'</button>'}
function textBtn(label,act,attrs=''){return '<button type="button" class="text-btn" data-act="'+act+'" '+attrs+'>'+e(label)+'</button>'}
function pill(s,k=''){return '<span class="badge '+e(k)+'">'+e(s)+'</span>'}
function folderPath(v){return String(v||'').replace(/\\/g,'/').split('/').filter(s=>s&&s!=='.').join('/')}
function lastName(v){return folderPath(v).split('/').filter(Boolean).at(-1)||'文件'}
function displayProject(){return S.project?.name || '尚未选择项目'}
function activeJobs(){return S.jobs.filter(j=>['queued','running'].includes(j.state||j.status))}
function summary(rows){return '<dl class="summary">'+rows.map(([k,v])=>'<div><dt>'+e(k)+'</dt><dd>'+e(v)+'</dd></div>').join('')+'</dl>'}
function banner(msg,warn=false){return '<div class="banner'+(warn?' warn':'')+'">'+e(msg)+'</div>'}
function humanSize(v){if(v===undefined || v===null || v==='')return '—';let n=Number(v);if(!Number.isFinite(n))return '—';for(const unit of ['B','KB','MB','GB','TB']){if(Math.abs(n)<1024||unit==='TB')return (n<10&&unit!=='B'?n.toFixed(1):Math.round(n))+' '+unit;n/=1024}}
function dateStr(v){if(v===undefined||v===null||v==='')return '';const d=new Date(typeof v==='number'&&v<1e11?v*1000:v);return Number.isNaN(d.getTime())?String(v):d.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}
const displayRef = r=>r?.name||r?.label||r?.id;
function refOf(id=S.draft.reference){return (S.boot.references||[]).find(v=>v.id===id)}
function param(key,fallback){return S.draft.params[key]??S.boot.defaults?.[key]??fallback??''}
function options(items,sel){return items.map(x=>{const [val,label]=Array.isArray(x)?x:[x,x];return '<option value="'+e(val)+'" '+(String(val)===String(sel)?'selected':'')+'>'+e(label)+'</option>'}).join('')}
function field(label,key,type,def,extras={}){
  const v=param(key,def), help=extras.help?'<span class="hint">'+e(extras.help)+'</span>':'';
  const common='data-param="'+e(key)+'" data-kind="'+type+'" ';
  let ctl;
  if(type==='select')ctl='<select '+common+'>'+options(extras.choices,v)+'</select>';
  else if(type==='boolean')ctl='<select '+common+'>'+options([['true','是'],['false','否']],v)+'</select>';
  else ctl='<input '+common+' type="'+(type==='number'?'number':'text')+'" '+(extras.step?'step="'+extras.step+'" ':'')+(extras.min!==undefined?'min="'+extras.min+'" ':'')+(extras.max!==undefined?'max="'+extras.max+'" ':'')+'value="'+e(Array.isArray(v)?v.join(', '):v)+'" placeholder="'+e(extras.placeholder||'')+'">';
  return '<label class="field '+(extras.full?'full':'')+'"><span>'+e(label)+'</span>'+ctl+help+'</label>';
}
function coreFields(){
  const ref=S.draft.reference,refs=S.boot.references||[],catalog=refs.filter(r=>!['custom','none'].includes(r.id));
  const list=[['none','尚未指定参考'],...catalog.map(r=>[r.id,displayRef(r)]),['custom','自定义基因集']];
  let s='<label class="field full"><span>参考基因集</span><select id="referenceSelect">'+options(list,ref)+'</select></label>';
  if(ref==='custom')s+='<label class="field full"><span>自定义参考文件路径</span><div class="inline"><input class="inline-input" id="customReference" value="'+e(S.draft.custom_reference)+'" placeholder="本机参考 TSV 或 JSON 文件">'+btn('浏览','custom-pick','folder')+btn('上传','stage-upload','install','','data-role="custom_reference"')+'</div></label>';
  const data=refOf();if(data){const u=data.source_url||data.source?.url; const url=typeof u==='string'&&/^https?:\/\//i.test(u)?u:'';
    s+='<div class="field full"><span class="hint">'+e([data.species,data.assembly].filter(Boolean).join(' · '))+(url?'　<a href="'+e(url)+'" target="_blank" rel="noopener noreferrer">参考来源</a>':'')+'</span></div>'}
  else if(ref==='none')s+='<p class="meta">选择与物种、组装版本匹配的参考后，可计算细胞器比例。</p>';
  if(S.draft.referenceNote)s+='<p class="hint">'+e(S.draft.referenceNote)+'</p>';
  return s;
}
function renderNav(){
  q('#workflowNav').innerHTML=steps.flatMap((s,i)=>s?['<button class="step-link '+(S.view==='work'&&S.step===i?'active':'')+'" data-step="'+i+'" '+(S.view==='work'&&S.step===i?'aria-current="step"':'')+'><span class="step-num">'+String(i).padStart(2,'0')+'</span>'+e(s[0])+'</button>']:[]).join('');
  qa('.nav').forEach(b=>{b.classList.toggle('active',b.dataset.view===S.view);if(b.dataset.view===S.view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  q('#crumb').textContent=({work:'分析工作台',panes:'分区工作区',files:'文件管理器',plots:'结果可视化',runs:'任务与接口'})[S.view];
  q('#projectName').textContent=S.project?.name||'选择或新建项目';
}
function hero(title,description,actions=''){return '<div class="hero"><div><h1>'+e(title)+'</h1><p class="sub">'+e(description)+'</p></div><div class="top-actions">'+actions+'</div></div>'}
function lastJobHTML(){
  if(!S.project)return empty('history','还没有运行记录','创建项目后，可在此查看任务进度。');
  const latest=S.jobs.find(stageMatchesJob);
  return latest?jobHTML(latest,true):empty('history','本步尚未运行','提交后可在此查看任务进度。');
}
function renderWork(){
  const [name,sub]=steps[S.step];
  const contents=[null,upstreamPage,qcPage,reprPage,clusterPage,runPage][S.step]();
  const project=S.project?.id||'';
  let layout=q('#workLayout');
  if(!layout||layout.dataset.project!==project){
    $main.innerHTML='<div id="workHero"></div><div id="workLayout" class="work-layout"><div id="workSettings" class="stack" tabindex="-1"></div>'+
      '<section id="workDock" aria-label="步骤内项目工作区"><div class="work-dock-head"><h2>'+icon('layers')+'项目工作区</h2>'+
      '<div class="inline">'+btn('分析设置','focus-work-settings','','mobile-stage-files')+btn('展开工作区','expand-workspace','zoom')+'</div></div><div id="workDockBody"></div></section></div>';
    layout=q('#workLayout');layout.dataset.project=project;
  }
  const changed=layout.dataset.step!==String(S.step);
  layout.dataset.step=S.step;
  q('#workHero').innerHTML=hero(name,sub,btn('本步文件','focus-stage-files','','mobile-stage-files')+btn('新建项目','new-project','plus'))+(S.error?banner(S.error,true):'');
  q('#workSettings').innerHTML=workflowGuide(S.step)+(stageRoles[S.step]?captureInputs():methodPanel())+contents;
  const fresh=mountDock(q('#workDockBody'));
  if(!fresh)q('#dock-stage').innerHTML=stageFilesPanel();
  setWorkExpansion(dock.expanded);
  if(fresh)loadFiles();
  if(fresh||changed){
    if(changed&&!visual.pinned){
      const candidate=outputJobs().find(j=>['quality','analysis','from_qc','recluster','pca','leiden','umap','quantify','read_qc'].includes(j.action));
      visual.job=candidate?.id||'';visual.plot=S.step===2?'qc':S.step===4?'umap':'';
    }
    loadPlots();
  }else renderExplorer();
  const previewAction=q('#dock-preview [data-preview-input]');
  if(previewAction&&dock.preview)previewAction.innerHTML=fileHandoffAction(dock.preview.path,dock.preview.scope);
  if(dock.left==='upstream')renderHandoffs();
  refreshStageFiles();
  if(S.step===2&&S.preview)chartPreview().catch(err=>toast(err.message,true));
}
function render(){
  renderNav();if(S.view==='work')renderWork();else if(S.view==='panes')renderDock();else if(S.view==='files')renderExplorer();else if(S.view==='plots')renderPlots();else renderRuns();
}
function go(view,step){
  S.view=view;if(step!==undefined)S.step=Math.max(1,Math.min(5,step)); q('#rail').classList.remove('open');
  syncRoute();
  if(view==='panes')loadDock();else if(view==='files')loadFiles();else if(view==='plots')loadPlots();else{render();if(view==='runs')pollJobs()}
  window.scrollTo({top:0,behavior:'instant'});
}

