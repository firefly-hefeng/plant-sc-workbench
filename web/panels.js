function nextButton(i){return '<div class="actions">'+btn('继续：'+steps[i][0],'go-step','arrow','soft','data-index="'+i+'"')+'</div>'}
function upstreamPage(){
  const available=stageLibraries(1).length>0;
  return card('FASTQ 定量','database','<div class="fields">'+
    field('定量引擎','quantifier','select','starsolo',{choices:[['starsolo','STARsolo 2.7.11b'],['cellranger','Cell Ranger 10']]})+
    field('建库与条码读段布局','chemistry','select','auto',{choices:[['auto','10x 3′ v3/v3.1 · 标准 12 nt UMI'],['SC3Pv3','明确指定 v3 · 12 nt UMI'],['SC3Pv3_10','已确认 v3 且 R1 截短 · 10 nt UMI（STARsolo）']]})+
    field('同时生成测序质量报告','run_read_qc','boolean',true)+
    (param('quantifier','starsolo')==='starsolo'?
      field('STAR 参考索引目录','star_index','text','',{full:true,placeholder:'已选 TAIR10 时可留空，使用内置索引'})+
      auxField('10x v3/v3.1 条码白名单（留空使用内置）','whitelist'):
    field('Cell Ranger 参考索引目录','reference_dir','text','',{full:true,placeholder:'包含 reference.json 与 star 目录的本地或计算端路径'}))+
    field('计入内含子读段','include_introns','boolean',true)+field('计算线程','threads','number',4,{min:1,step:1})+
    field('可用内存（GB）','memory_gb','number',16,{min:1,step:1})+'</div><div class="actions">'+btn('测序质量检查','job-read_qc','report','',available?'':'disabled')+btn('运行定量','job-quantify','play','primary',available?'':'disabled')+'</div>')+
    card('自建参考索引','leaf','<details><summary>使用 FASTA 与 GTF 为选定引擎构建参考</summary><div class="fields section-gap">'+auxField('基因组 FASTA','fasta')+auxField('基因注释 GTF','gtf')+field('参考名称','ref_name','text','plant_reference',{full:true})+'</div><div class="actions">'+btn('构建参考','job-build_reference','play')+'</div></details>')+nextButton(2);
}
function qcPage(){
  const f=field;
  return card('按捕获预览过滤条件','sliders','<div class="fields">'+
    f('最少 UMI 数','min_counts','number','',{min:0,step:1})+f('最少检测基因数','min_genes','number','',{min:0,step:1})+
    f('MAD 倍数','mad_multiplier','number',4,{min:0,step:0.1,help:'依据各捕获自身分布计算候选阈值。'})+
    f('线粒体比例上限（%）','max_mito_pct','number','',{min:0,max:100,step:0.1,placeholder:'可留空'})+
    f('质体比例上限（%）','max_plastid_pct','number','',{min:0,max:100,step:0.1,placeholder:'可留空'})+
    '</div><div class="actions">'+btn('计算过滤预览','qc-preview','report','primary')+btn('执行清洗并保存对象','job-quality','install')+'</div><div id="qcPreview">'+qcPreviewHTML()+'</div>')+
    card('双细胞与环境 RNA','layers','<div class="fields">'+
    f('双细胞处理','doublet_mode','select','report',{choices:[['report','仅报告预测'],['remove','移除预测双细胞'],['off','跳过检测']]})+
    f('预期双细胞率（0–1）','expected_doublet_rate','number','',{min:0,max:1,step:0.01,placeholder:'依软件默认或文库信息'})+
    f('有效条码调用','cell_calling','select','upstream',{choices:[['upstream','沿用上游名单（仅 raw 时运行 emptyDrops）'],['emptydrops','用 emptyDrops 重新调用']]})+
    f('环境 RNA 校正','ambient_mode','select','off',{choices:[['off','保留原始计数'],['soupx','SoupX 校正（需 raw 液滴）']]})+
    auxField('SoupX 粗分群 TSV（可选）','clusters_tsv')+
    f('背景 UMI 上界（emptyDrops）','lower','number',100,{min:1,step:1})+
    f('液滴调用 FDR','fdr','number',0.01,{min:0.0001,max:0.99,step:0.0001})+
    '</div><p class="note">双细胞按物理捕获评估。SoupX 使用同一捕获的背景液滴与候选细胞，自动生成临时粗聚类，也可在文库设置中指定分组。</p>')+(stageLibraries(2).length?'<div class="actions">'+btn('按当前文库运行全流程','job-analysis','play')+'</div>':'')+nextButton(3);
}
function qcPreviewHTML(){
  if(!S.preview)return '';
  const t=S.preview, libs=t.libraries||[];let out='<div class="rule"></div><h3>过滤预览</h3><p class="hint">双细胞处理前：输入 '+e(nfmt(t.input_cells))+' 个，保留 '+e(nfmt(t.retained_cells))+' 个。</p>';
  out+='<div class="scroll section-gap"><table class="table"><thead><tr><th>捕获</th><th>输入</th><th>保留</th><th>UMI 中位数</th><th>基因中位数</th></tr></thead><tbody>'+libs.map(l=>'<tr>'+[l.id,l.input_cells,l.retained_cells,l.median_counts,l.median_genes].map(x=>'<td>'+e(nfmt(x))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  for(const l of libs){const counts=l.rule_counts||{};if(Object.keys(counts).length){out+='<details class="accordion"><summary>'+e(l.id)+' · 逐条规则命中数</summary>'+summary(Object.entries(counts).map(([k,v])=>[k,nfmt(v)]))+'</details>'}}
  if(Array.isArray(t.warnings)&&t.warnings.length)out+=banner(t.warnings.join('；'),true);
  out+='<div id="qcScatter" style="min-height:250px"></div><p class="hint">散点图每个捕获最多展示 250 个条码。上表使用全部条码，预览发生在双细胞处理之前。</p>';
  return out;
}
function qualityParentCard(){
  const runs=S.jobs.filter(j=>j.state==='succeeded'&&j.action==='quality');
  if(!runs.length)return '';
  return card('从已清洗的对象继续','layers','<label class="field"><span>质控来源任务</span><select id="qualityParent">'+options(runs.map(j=>[j.id,j.id+'　'+dateStr(j.created)]),stageBinding().qualityParent||runs[0].id)+'</select></label><p class="hint">沿用该任务的条码和原始计数，按当前特征、降维和分群设置生成新结果。</p><div class="actions">'+btn('继续降维与聚类','job-from_qc','play','soft')+'</div>');
}
function reprPage(){return card('特征与主成分','layers','<div class="fields">'+
  field('高变基因数','hvg','number',2000,{min:3,step:1})+field('主成分数','n_pcs','number',30,{min:2,step:1})+
  field('选择高变基因的方法','hvg_method','select','seurat',{choices:[['seurat','Seurat 离散度 · 对数表达'],['seurat_v3','Seurat v3 · 整数计数']]})+
  field('用于建图的表达层','analysis_layer','select','counts',{choices:[['counts','原始计数'],['soupx','SoupX 校正层']]})+
  field('多文库基因集合','feature_join','select','strict',{choices:[['strict','要求一致的基因集合'],['intersection','取明确交集（报告损失）']]})+
  field('批次校正','integration','select','none',{choices:[['none','保留未整合表示'],['harmony','Harmony 批次校正']]})+
  '</div><div class="rule"></div><p class="meta">批次和处理条件在文库信息中设置。请检查两者能否区分，再比较校正前后的样本结构。</p>')+qualityParentCard()+nextButton(4)}
function clusterPage(){
  const matches=S.jobs.filter(j=>(j.state||j.status)==='succeeded'&&['analysis','from_qc','recluster'].includes(j.action||'analysis'));
  return card('邻居图与 Leiden 分区','compare','<div class="fields">'+field('每个细胞的邻居数','n_neighbors','number',15,{min:2,step:1})+
  field('建图使用的表示','graph_representation','select','auto',{choices:[['auto','沿用流程选择'],['X_pca','原始 PCA'],['X_pca_harmony','Harmony 校正后的 PCA']]})+
  field('随机种子','seed','number',42,{min:0,step:1})+field('Leiden 分辨率','resolutions','array',[0.5,1],{full:true,placeholder:'0.4, 0.8, 1.2',help:'多个值用逗号分隔；在同一张邻居图上比较。'})+'</div>')+
  (matches.length?card('复用已有邻居图','compare','<label class="field"><span>来源任务</span><select id="parentJob">'+options(matches.map(j=>[j.id,j.id+'　'+dateStr(j.created)]),stageBinding().parentJob||matches[0].id)+'</select></label><div class="actions">'+btn('比较当前分辨率','recluster','compare','soft')+'</div>'):'')+nextButton(5);
}
function runPage(){const libs=stageLibraries(5),m=libs.filter(l=>l.kind!=='fastq');return card('运行检查','check',summary([['输入文库',libs.length+' 个'],['矩阵文库',m.length+' 个'],['参考基因集',displayRef(refOf())||S.draft.reference],['批次校正',param('integration','none')],['分辨率',[param('resolutions',[0.5,1])].flat().join(' / ')]] )+
  '<div class="rule"></div><p class="meta">从已有输入开始运行，分析对象、图、表和参数保存到本次任务的结果目录。</p><div class="actions">'+btn('运行完整分析','job-analysis','play','primary')+'</div>')+methodPanel()+recipeForm()+
  card('结果文件','folder', '<p class="meta">在项目目录中浏览分析对象、图片、QC 表和聚类结果。选择已完成任务可直接打开它的结果目录。</p><div class="actions">'+btn('打开文件管理器','files','folder')+'</div>');}
function jobHTML(j,compact=false){
  const state=j.state||j.status,percent=Number(j.progress),done=state==='succeeded',act={analysis:'完整分析',quality:'质控与清洗',from_qc:'从清洗对象继续',quantify:'FASTQ 定量',build_reference:'构建参考',read_qc:'测序质量检查',recluster:'聚类比较'}[j.action]||jobNames[j.action]||'分析任务';
  const note=j.message||j.error||'';const message=typeof note==='object'?(note.message||JSON.stringify(note)):note;
  return '<article class="job"><div class="between"><strong class="row-name">'+e(act)+'</strong>'+pill(jobLabels[state]||state,state)+'</div><span class="minor break">'+e(dateStr(j.created||j.created_at))+(compact?'':' · '+e(j.id))+'</span>'+
  (['running','queued'].includes(state)&&Number.isFinite(percent)?'<div class="progress" role="progressbar" aria-label="运行进度" aria-valuenow="'+Math.round(percent)+'"><b style="width:'+Math.max(0,Math.min(100,percent))+'%"></b></div>':'')+
  (message?'<span class="'+(state==='failed'?'block-error':'hint break')+'">'+e(message)+'</span>':'')+
  '<div class="job-actions">'+textBtn('输入与输出','task-io','data-id="'+e(j.id)+'"')+(done&&['analysis','quality','from_qc','recluster','read_qc','quantify','pca','umap','leiden'].includes(j.action)?textBtn('查看图表','view-plots','data-id="'+e(j.id)+'"'):'')+(done&&j.output?textBtn('查看结果','open-output','data-path="'+e(j.output)+'"'):'')+(done&&['analysis','quality','from_qc','recluster'].includes(j.action)?textBtn('质控摘要','run-summary','data-id="'+e(j.id)+'"'):'')+(done&&['analysis','from_qc','recluster'].includes(j.action)?textBtn('交互聚类图','view-embedding','data-id="'+e(j.id)+'"'):'')+(['running','queued'].includes(state)?textBtn('取消任务','cancel-job','data-id="'+e(j.id)+'"'):'')+'</div></article>';
}
function renderRuns(){
  $main.innerHTML=hero('任务与接口','查看每次运行的输入、输出和计算状态。',btn('刷新','refresh-jobs','refresh'))+
  '<div id="queueState" class="hint"></div>'+card('项目任务','history','<div id="jobsList">'+(S.jobs.length?S.jobs.map(j=>jobHTML(j)).join(''):empty('history','还没有运行记录',S.project?'完成设置后可提交分析。':'请先选择或创建项目。'))+'</div>',pill(S.jobs.length+' 项'));
}

