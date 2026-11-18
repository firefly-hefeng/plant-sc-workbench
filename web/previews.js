/* The explorer, workflow panes and gallery use the same scoped file reader. */
const previewTypes={dir:'目录',image:'图像',table:'表格',text:'文本',binary:'文件',markdown:'文档',pdf:'PDF',report:'网页报告',matrix:'矩阵对象',archive:'压缩包',parquet:'Parquet 表'};
function entryType(file){
  if(file.is_dir||['dir','directory'].includes(file.type))return 'dir';
  const name=file.name.toLowerCase(), logical=name.replace(/\.gz$/,'');
  if(/\.(html?|pdf)$/.test(name))return name.endsWith('.pdf')?'pdf':'report';
  if(/\.(png|jpe?g|gif|webp|svg|bmp|avif|ico)$/.test(name))return 'image';
  if(/\.(h5ad|h5|hdf5)$/.test(name))return 'matrix';
  if(name.endsWith('.zip'))return 'archive';
  if(name.endsWith('.parquet'))return 'parquet';
  if(/\.(csv|tsv|tab)$/.test(logical))return 'table';
  if(/\.(md|markdown)$/.test(logical))return 'markdown';
  if(/\.(txt|log|out|stats|jsonl?|ya?ml|py|r|sh|ps1|toml|ini|cfg|xml|mtx|fastq|fq|fasta|fa|fna|gtf|gff3?|bed|sam|vcf|rmd|rproj)$/.test(logical))return 'text';
  return 'binary';
}
function localDocTarget(raw,path){
  if(!raw||raw.startsWith('//')||/^[a-z][a-z\d+.-]*:/i.test(raw)||raw.includes('\\'))return null;
  // Keep document links in the same registered project or library, including nested directories.
  const base='https://document.invalid/';
  const url=new URL(raw,base+path.split('/').map(encodeURIComponent).join('/'));
  return url.origin===new URL(base).origin?{path:decodeURIComponent(url.pathname.slice(1)),hash:url.hash}:null;
}
const markdownReader=window.markdownit({html:false,linkify:false});
function markdownBody(source,args){
  const article=document.createElement('article');article.className='native-markdown';const template=document.createElement('template');template.innerHTML=markdownReader.render(source);
  const content=template.content;
  const headings=new Map();
  for(const el of content.querySelectorAll('h1,h2,h3,h4,h5,h6')){
    const slug=el.textContent.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu,'').replace(/\s+/g,'-');
    const count=headings.get(slug)||0;headings.set(slug,count+1);el.dataset.heading=count?slug+'-'+count:slug;
  }
  for(const el of content.querySelectorAll('a,img')){
    const image=el.tagName==='IMG',attr=image?'src':'href',raw=el.getAttribute(attr)||'';
    if(!image&&/^https?:\/\//i.test(raw)){el.target='_blank';el.rel='noopener noreferrer';continue}
    let target;try{target=localDocTarget(raw,args.path)}catch{}
    if(!target){if(image)el.replaceWith(el.alt||'外部图片');else el.removeAttribute(attr);continue}
    const url=query('/api/file',{...args,path:target.path});
    el.setAttribute(attr,url);
    if(!image){
      el.dataset.documentLink=target.path;
      if(target.hash)el.dataset.fragment=target.hash.slice(1);
    }else{el.loading='lazy';el.alt=el.alt||'文档插图'}
  }
  article.append(content);return article;
}
function jumpHeading(host,fragment){
  if(!fragment)return;
  let slug=fragment;try{slug=decodeURIComponent(fragment)}catch{}
  const heading=[...host.querySelectorAll('[data-heading]')].find(el=>el.dataset.heading===slug);
  heading?.scrollIntoView({block:'nearest'});
}
function previewTable(data){
  return '<div class="dock-table"><table class="table"><thead><tr>'+data.columns.map(c=>'<th>'+e(c)+'</th>').join('')+'</tr></thead><tbody>'+data.rows.map(row=>'<tr>'+row.map(v=>'<td>'+e(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
async function readPreview(host,args,onOpen,fragment='',toolbar=null){
  const name=lastName(args.path),kind=entryType({name});
  try{
    if(kind==='image'){
      host.innerHTML='<div class="dock-image"><button type="button" class="preview-image-button" aria-label="放大查看 '+e(name)+'"><img alt="'+e(name)+'" src="'+e(query('/api/file',args))+'"></button></div>';
      host.querySelector('button').onclick=()=>showImage({name,path:args.path},false,args);return;
    }
    if(kind==='binary'){host.innerHTML=empty('file','此格式可下载查看','使用上方或下方的下载按钮保存原文件。');return}
    host.innerHTML='<p class="preview-note" role="status">正在读取预览…</p>';
    if(kind==='report'||kind==='pdf'){
      const {url}=await api(query('/api/native-preview',args));if(!host.isConnected)return;
      const frame=document.createElement('iframe');
      frame.className='native-frame';frame.title=name;frame.referrerPolicy='no-referrer';
      if(kind==='report')frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-downloads');
      frame.src=url;
      const link='<a class="btn native-expand" href="'+e(url)+'" target="_blank" rel="noopener noreferrer">整页阅读 ↗</a>';
      if(toolbar){toolbar.insertAdjacentHTML('afterbegin',link);host.replaceChildren()}
      else host.innerHTML='<div class="native-tools"><span>'+previewTypes[kind]+'</span>'+link+'</div>';
      host.append(frame);return;
    }
    const r=await api(query('/api/preview',args));if(!host.isConnected)return;
    host.replaceChildren();
    if(r.note){const note=document.createElement('p');note.className='preview-note';note.textContent=r.note;host.append(note)}
    if(kind==='markdown'){
      const article=markdownBody(r.text,args);
      article.addEventListener('click',event=>{
        const link=event.target.closest('[data-document-link]');if(!link)return;
        event.preventDefault();
        if(link.dataset.documentLink===args.path&&link.dataset.fragment)jumpHeading(article,link.dataset.fragment);
        else onOpen(link.dataset.documentLink,link.dataset.fragment||'');
      });
      host.append(article);jumpHeading(host,fragment);
    }else if(Array.isArray(r.columns)){
      if(r.sample){
        host.insertAdjacentHTML('beforeend','<details class="preview-schema"><summary>查看字段与类型</summary>'+previewTable(r)+'</details><p class="preview-note">数据样例 · 首个行组的前 '+r.sample.rows.length+' 行，'+r.sample.columns.length+' 个简单字段；长字段在预览中省略。</p>'+previewTable(r.sample));
      }else host.insertAdjacentHTML('beforeend',previewTable(r));
      if(!r.rows.length)host.insertAdjacentHTML('beforeend','<p class="preview-note">没有可展示的数据行。</p>');
    }else{
      const pre=document.createElement('pre');pre.className='preview-text';pre.textContent=r.text||'';host.append(pre);
    }
    if(r.truncated)host.insertAdjacentHTML('beforeend','<p class="preview-note">当前仅显示开头部分，可下载完整文件。</p>');
  }catch(err){if(host.isConnected)host.innerHTML=banner(err.message,true)}
}

