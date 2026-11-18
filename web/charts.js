let plotLibrary;
function getPlotly(){
  if(!plotLibrary)plotLibrary=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='/vendor/plotly-basic.min.js';
    script.onload=()=>resolve(window.Plotly);script.onerror=()=>{plotLibrary=null;reject(Error('无法载入本地绘图库。'))};document.head.appendChild(script);
  });return plotLibrary;
}
const chartColors=['#176a58','#bd6640','#5383ba','#9974ad','#998444','#54a39d','#bd7990','#607a43','#846953','#6673a2'];
async function renderPartition(url,host){
  const response=await fetch(url);
  if(!response.ok)throw Error('比较表读取失败');
  const [header,...lines]=(await response.text()).trim().split(/\r?\n/).map(line=>line.split('\t'));
  const cols=['left','right','ARI'].map(name=>header.indexOf(name));
  if(cols.includes(-1))throw Error('来源表缺少分区或 ARI 字段');
  const labels=lines.map(r=>r[cols[0]]+' / '+r[cols[1]]);
  const scores=lines.map(r=>Number(r[cols[2]]));
  const P=await getPlotly();
  if(!host.isConnected)return;
  await P.newPlot(host,[{type:'bar',orientation:'h',x:scores,y:labels,marker:{color:'#30775d'},hovertemplate:'%{y}<br>ARI %{x:.4f}<extra></extra>'}],
    {height:Math.max(host.closest('#workDock')&&dock.focus!=='right'?220:330,lines.length*23+90),margin:{l:12,r:30,t:14,b:55},xaxis:{title:{text:'Adjusted Rand index'},range:[Math.min(0,...scores),1.02]},yaxis:{automargin:true,autorange:'reversed'},font:{family:'system-ui',size:11}},
    {displaylogo:false,responsive:true});
}
async function renderEmbedding(id,host){
  const data=await api(query('/api/embedding',{project:S.project.id,job:id}));
  const P=await getPlotly();
  if(!host.isConnected)return;
  host.innerHTML='<div class="between plot-controls"><label class="inline">着色字段 <select id="colorBy" class="inline-input">'+options(data.groups,data.groups.includes('leiden')?'leiden':data.groups.includes('sample')?'sample':data.groups[0])+'</select></label><span class="hint">'+data.rows.length.toLocaleString()+' / '+data.total.toLocaleString()+' 个条码</span></div><div id="embeddingPlot" class="embed-canvas"></div><p class="hint" id="pickedCluster">点击散点查看条码和该组的完整成员数。</p>';
  const canvas=host.querySelector('#embeddingPlot'),chooser=host.querySelector('#colorBy');
  async function draw(){
    const key=chooser.value,idx=data.columns.indexOf(key),groups=new Map();
    for(const r of data.rows){const k=r[idx];if(!groups.has(k))groups.set(k,{x:[],y:[],ids:[]});const g=groups.get(k);g.x.push(+r[1]);g.y.push(+r[2]);g.ids.push(r[0]);}
    const series=Array.from(groups).sort(([a],[b])=>a.localeCompare(b,undefined,{numeric:true})).map(([name,v],i)=>({type:'scatter',mode:'markers',name,x:v.x,y:v.y,customdata:v.ids,marker:{size:5,color:chartColors[i%chartColors.length],opacity:.78},hovertemplate:'%{customdata}<br>UMAP 1 %{x:.2f}<br>UMAP 2 %{y:.2f}<extra></extra>'}));
    await P.react(canvas,series,{margin:{l:48,r:12,t:14,b:76},xaxis:{title:{text:'UMAP 1'},zeroline:false},yaxis:{title:{text:'UMAP 2'},zeroline:false,scaleanchor:'x'},legend:{orientation:'h',y:-0.19},hovermode:'closest',font:{family:'system-ui',size:11}},{displaylogo:false,responsive:true,scrollZoom:true});
    if(!canvas.isConnected)return;
    canvas.removeAllListeners('plotly_click');
    canvas.on('plotly_click',e=>{const p=e.points[0];host.querySelector('#pickedCluster').textContent=p.customdata+' · '+key+' = '+p.data.name+' · 全对象成员 '+data.counts[key][p.data.name]+' 个。';});
  }
  chooser.onchange=()=>draw().catch(e=>toast(e.message,true));await draw();
}
async function chartPreview(){
  if(!S.preview)return;
  const P=await getPlotly();
  const div=document.querySelector('#qcScatter');if(!div)return;
  const series=S.preview.libraries.flatMap((lib,i)=>[true,false].map(keep=>{
    const pts=(lib.preview_points||[]).filter(x=>Boolean(x[2])===keep);
    return {type:'scatter',mode:'markers',name:lib.id+(keep?' · 保留':' · 排除'),x:pts.map(r=>r[0]),y:pts.map(r=>r[1]),marker:{size:5,opacity:.7,color:keep?chartColors[i%chartColors.length]:'#cb6748'}};
  }).filter(s=>s.x.length));
  await P.newPlot(div,series,{margin:{l:52,r:12,t:12,b:42},xaxis:{title:{text:'每条码 UMI'}},yaxis:{title:{text:'检测基因数'}},legend:{orientation:'h',y:-0.19},font:{family:'system-ui',size:10}},{displaylogo:false,responsive:true});
}


async function showScientificSummary(id){
  const data=await api(query('/api/run-summary',{project:S.project.id,job:id}));
  const rows=data.libraries.map(lib=>{
    const d=lib.doublets||{};
    const predicted=d.status==='scored'?nfmt(d.predicted)+' / '+nfmt(d.eligible):({disabled:'已关闭',off:'已关闭',not_assessed:'未评估',scores_only:'仅分数'}[d.status]||d.status||'未评估');
    return '<tr>'+[lib.id,nfmt(lib.input_cells),nfmt(lib.retained_cells),nfmt(lib.median_counts),nfmt(lib.median_genes),predicted].map(v=>'<td>'+e(v)+'</td>').join('')+'</tr>';
  }).join('');
  const table='<div class="scroll"><table class="table"><thead><tr>'+['捕获','候选条码','保留','UMI 中位数','基因数中位数','预测双细胞 / 参与评分'].map(v=>'<th>'+v+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
  const notes=(data.warnings||[]).map(v=>'<li>'+e(v)+'</li>').join('');
  const detail=summary([['保留条码',nfmt(data.retained_cells)+' / '+nfmt(data.input_cells)],['分析基因数',nfmt(data.genes)]]);
  modalShow('质控摘要',detail+'<div class="rule"></div>'+table+(notes?'<h3 class="section-gap">需要复核</h3><ul>'+notes+'</ul>':''),'qc-summary',true);
}
