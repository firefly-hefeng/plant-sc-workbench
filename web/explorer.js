const explorerTree=new Map();
const expandedDirs=new Set(['']);
let treeScope='', fileOrder='name';
function scopeKey(){return [S.project?.id,S.scope,S.scopeLibrary].join(':')}
function resetTree(){
  treeScope=scopeKey();explorerTree.clear();expandedDirs.clear();expandedDirs.add('');
}
function rememberTree(path,entries){
  if(treeScope!==scopeKey())resetTree();
  explorerTree.set(path,entries.filter(f=>entryType(f)==='dir'));
  let ancestor='';
  for(const part of path.split('/').filter(Boolean)){ancestor=[ancestor,part].filter(Boolean).join('/');expandedDirs.add(ancestor)}
}
function sortEntries(entries){
  return [...entries].sort((a,b)=>Number(entryType(b)==='dir')-Number(entryType(a)==='dir')||
    (fileOrder==='size'?b.size-a.size:fileOrder==='recent'?String(b.mtime).localeCompare(String(a.mtime)):0)||
    a.name.localeCompare(b.name,'zh-CN',{numeric:true}));
}
async function getTree(path){
  const key=scopeKey();
  const r=await api(query('/api/files',fileArgs(path)));
  if(key!==scopeKey()||S.view!=='files'&&!isDockView())return;
  explorerTree.set(path,r.entries.filter(x=>x.type==='dir'));
  const target=q('#folderTree');if(target)target.innerHTML=folderTreeHTML();
}
function folderTreeHTML(){
  function item(path,name,depth){
    const open=expandedDirs.has(path),active=path===S.dir;
    const kids=explorerTree.get(path);
    const job=S.scope==='project'&&path.startsWith('runs/')&&path.split('/').length===2?S.jobs.find(j=>j.id===name):null;
    const title=job?(jobNames[job.action]||job.action)+' · '+job.id.slice(0,6):name;
    return '<div class="tree-line '+(active?'selected':'')+'" style="--depth:'+depth+'"><button class="twist" data-act="expand-dir" data-path="'+e(path)+'" aria-label="'+(open?'折叠':'展开')+' '+e(name)+'" aria-expanded="'+open+'">'+icon(open?'down':'right')+'</button><button class="tree-title" data-act="open-dir" data-path="'+e(path)+'" title="'+e(name)+'">'+icon(open?'folderOpen':'folder')+e(title)+'</button></div>'+
      (open&&kids?kids.map(x=>item(x.path,x.name,depth+1)).join(''):'');
  }
  return item('',S.scope==='input'?(fileSources().find(([id])=>id==='input:'+S.scopeLibrary)?.[1]||'输入目录'):'项目根目录',0);
}
function renderExplorer(){
  const target=isDockView()?q('#dock-files'):$main;
  if(!target)return;
  if(!S.project){target.innerHTML=hero('文件管理器','')+empty('folder','尚未选择项目','打开或创建工作项目后即可浏览文件。');return}
  if(treeScope!==scopeKey())resetTree();
  const crumbs=folderPath(S.dir).split('/').filter(Boolean);
  const crumb='<button data-act="open-dir" data-path="">'+(S.scope==='input'?'输入目录':'项目')+'</button>'+crumbs.map((s,i)=>'<span>/</span><button data-act="open-dir" data-path="'+e(crumbs.slice(0,i+1).join('/'))+'">'+e(s)+'</button>').join('');
  const held=S.scope==='input'||S.dir==='runs'||S.dir.startsWith('runs/');
  const controls=btn('在系统中打开','reveal-dir','folderOpen')+btn('新建文件夹','mkdir-dialog','plus','primary',held?'disabled':'');
  const header=isDockView()?'<div class="dock-actions">'+controls+'</div>':hero('文件管理器',displayProject(),controls);
  const tree='<aside class="explorer-side">'+(isDockView()?'<button class="btn" data-dock-tree aria-expanded="'+dock.tree+'">'+icon('folder')+'目录树</button>':'<div class="pane-heading">目录树</div>')+'<select id="fileSource" class="inline-input" aria-label="文件来源">'+options(fileSources(),S.scope==='input'?'input:'+S.scopeLibrary:'project')+'</select><div id="folderTree">'+folderTreeHTML()+'</div></aside>';
  const tools='<div class="file-actions"><input id="fileFilter" class="inline-input" aria-label="筛选本目录文件" placeholder="筛选文件名称…" value="'+e(S.fileFilter)+'"><div class="inline"><select id="fileOrder" aria-label="文件排序" class="inline-input">'+options([['name','名称排序'],['recent','最近修改'],['size','文件大小']],fileOrder)+'</select>'+btn('列表','list','files',S.fileMode==='list'?'soft':'')+btn('缩略图','gallery','picture',S.fileMode==='gallery'?'soft':'')+'</div></div>';
  const listing=S.fileError?banner(S.fileError,true):S.loadingFiles?empty('folder','正在读取目录',''):fileRows();
  target.innerHTML=header+'<div class="explorer-shell">'+tree+'<section class="explorer-list"><div class="pathbar"><button data-act="up-dir" aria-label="上一级" '+(!S.dir?'disabled':'')+'>↑</button>'+icon('folder')+crumb+'<span class="fill"></span>'+btn('刷新','refresh-files','refresh')+'</div>'+tools+'<div id="fileRows">'+listing+'</div><footer class="pane-foot"><span>'+S.files.length+' 项</span>'+btn('复制目录路径','copy-dir-path')+'</footer></section></div>';
  if(!S.loadingFiles&&!S.fileError){
    warmDirectoryHandoffs();
    for(const dir of expandedDirs)if(!explorerTree.has(dir))getTree(dir).catch(err=>toast(err.message,true));
  }
}
function fileOperation(kind,source=''){
  const copy=kind==='copy';
  const dir=copy?'':S.dir;
  const initial=copy?source.split('/').pop():'';
  const content='<form id="fileActionForm"><div class="fields"><label class="field full">项目内目标目录<input id="targetDirectory" value="'+e(dir)+'" placeholder="留空使用项目根目录"></label><label class="field full">'+(copy?'副本名称':'文件夹名称')+'<input id="targetName" required value="'+e(initial)+'"></label></div><p id="fileActionError" class="block-error"></p><div class="actions"><button class="btn primary" type="submit">'+(copy?'复制文件':'创建文件夹')+'</button></div></form>';
  modalShow(copy?'复制到项目':'新建文件夹',content,'filesystem');
  const pid=S.project.id, sourceArgs=fileArgs(source);
  q('#targetName').focus();
  q('#fileActionForm').onsubmit=async ev=>{
    ev.preventDefault();const button=ev.target.querySelector('[type=submit]');button.disabled=true;
    try{
      const directory=q('#targetDirectory').value.trim(),name=q('#targetName').value;
      await api('/api/files/'+(copy?'copy':'mkdir'),{...(copy?sourceArgs:{project:pid}),directory,name});
      if(S.project?.id!==pid)return;
      dlg.close();S.scope='project';S.scopeLibrary='';resetTree();openDir(directory);
      toast(copy?'已复制文件':'已创建文件夹');
    }catch(err){q('#fileActionError').textContent=err.message;button.disabled=false}
  };
}

