/* Guidance follows the same entry points and deliverables as the five work positions. */
const workflowGuides=[
  null,
  {question:'我的测序读段能否生成可信的计数矩阵？',intro:'从成对的 FASTQ 开始。已有 10x 矩阵或含原始计数的 H5AD，可直接进入质控。',
   input:'按一次物理捕获登记一份文库，区分样本和批次。核对物种、参考基因组版本、建库方法及 R1/R2 文件。',
   action:'先运行测序质检。在 FastQC 的 Basic Statistics 中核对两端的读段数和读长，在 MultiQC 中比较各文库。10x 3′ 文库的 R1 含条码和 UMI，R2 读转录本，需分别解读两端的碱基组成。',
   check:'确认条码与 UMI 在实际 R1 长度内，再运行定量。若读段长度与建库说明不符，先查样本记录。单核数据还需核对是否计入内含子。',
   handoff:'在质控页的「上游输出」选择定量矩阵。filtered 保存候选条码，raw 还保留背景液滴，可供重新调用条码或估计环境 RNA。'},
  {question:'这一批条码里，哪些细胞或细胞核值得保留？',intro:'先按捕获预览过滤对细胞数的影响，再决定是否执行清洗。可以从定量结果或现成的计数矩阵开始。',
   input:'接入同一参考版本的计数矩阵，为每次捕获注明样本与单细胞或单核模态。已有对数归一化对象时，先确认原始计数所在的层。',
   action:'点击「计算过滤预览」，逐个捕获比较 UMI 总数、检测到的基因数和保留比例。UMI 是用于区分原始 RNA 分子的标签；基因数表示这个条码里检测到了多少种基因。',
   check:'结合物种、组织和模态解读线粒体与质体比例。比例接近零时先核对参考基因匹配。查看哪些规则命中最多；若某个样本损失特别大，回看它的分布和建库记录。双细胞预测可先仅报告。',
   handoff:'确认保留范围后执行清洗。qc_libraries.tsv 可核对各捕获的保留数；在降维页选择这次任务的 qc.h5ad 作为特征选择输入。'},
  {question:'怎样保留主要的表达差异，让细胞之间可以比较？',intro:'先将细胞置于可比较的表达尺度，筛选高变基因，再用主成分概括主要差异。',
   input:'从清洗对象开始可选择「归一化与高变基因」。已有对数表达和高变基因标记的 H5AD 可从「主成分与批次诊断」开始。',
   action:'先运行特征选择，再将其输出交给 PCA。高变基因是细胞间变化较明显的基因；主成分把许多基因共同的变化概括为少数几个坐标。',
   check:'查看各主成分解释的方差及不同样本的分布。若批次与处理条件完全重合，数据本身难以区分二者。启用 Harmony 前，先保留未校正结果作比较。',
   handoff:'向邻居图模块传递含 PCA 坐标的 H5AD。使用 Harmony 时核对下游建图采用的是哪组坐标。'},
  {question:'细胞在不同分辨率下，是否仍然分在一起？',intro:'用主成分寻找相似细胞，建立邻居图。UMAP 用于看结构，Leiden 在图上给细胞分组。',
   input:'已有主成分时从「邻居图」开始；已有邻居图时，可分别运行 UMAP 和 Leiden，两者复用同一张图。',
   action:'在同一张图上比较多个 Leiden 分辨率。分辨率升高通常会得到更细的分组。在 UMAP 上按簇和捕获分别着色，检查结构是否被单一文库主导。',
   check:'对照分区一致性（ARI）和成员重叠表，找出稳定的群和容易拆分的群。二维图上的距离和簇编号本身不足以判断细胞类型。',
   handoff:'记录所选分辨率、邻居数和随机种子。完整运行后，在 cells.tsv 中核对每个细胞的坐标与分群，再进入交付。'},
  {question:'交给合作者的结果，能否追溯到同一批输入和参数？',intro:'这里可以从登记的文库运行完整流程，也可以复用已有对象，只运行所需模块。',
   input:'先核对捕获、样本、参考版本及关键参数。若前面已经完成计算，可直接选择成功任务检查结果。',
   action:'在「任务与接口」打开该次任务的「输入与输出」，核对来源、参数和产物。在图表区打开分析报告，在文件区查看同一次任务的表格和对象。',
   check:'完整分析时，对照质控汇总、细胞表和对象维度；确认保留细胞数、样本标识和分辨率一致。单模块运行时按该模块的输出清单验收。',
   handoff:'交付完整分析的 analysis.h5ad、cells.tsv、报告及任务记录，或单模块的 component.h5ad 和对应记录。后续细胞类型注释从选定的对象与分群开始。'}
];
const moduleGuidance={
  features:'将每个细胞的表达量换算到可比较的尺度，标记高变基因。输出供 PCA 使用。',
  pca:'把高变基因的表达压缩为主成分，检查各主成分解释的方差。输出供邻居图使用。',
  graph:'按低维坐标寻找表达相近的细胞，写入距离和连接权重。UMAP 和 Leiden 都使用这张图。',
  umap:'把邻居图投影到二维，用于观察群体、样本及批次分布；细胞的分群标签由 Leiden 生成。',
  leiden:'在邻居图上按所选分辨率分群。比较不同分辨率下哪些细胞仍聚在一起，再选定待注释的分区。'
};
const guideState=new Map();
function workflowGuide(step){
  const g=workflowGuides[step];
  const facts=[['输入准备',g.input],['如何操作',g.action],['如何判断',g.check],['交给下一步',g.handoff]];
  return '<section class="workflow-guide" aria-label="本步分析导读"><div class="guide-title"><h2>'+e(g.question)+'</h2><button type="button" class="text-btn" data-act="workflow-overview">流程全览</button></div><p>'+e(g.intro)+'</p>'+
    '<details data-guide-step="'+step+'" '+(guideState.get(step)?'open':'')+'><summary>查看本步操作与判断依据</summary><dl>'+facts.map(([k,v])=>'<dt>'+e(k)+'</dt><dd>'+e(v)+'</dd>').join('')+'</dl></details></section>';
}
function workflowOverview(){
  const routes=[
    ['成对 FASTQ','按捕获生成计数矩阵','已有原始计数矩阵，可直接从质控开始。'],
    ['计数矩阵','清洗后的细胞或细胞核','复核每个捕获的过滤影响，保存质控对象。'],
    ['清洗对象','高变基因与主成分','用主要表达差异来比较细胞，可在此检查批次效应。'],
    ['主成分','邻居图、UMAP 与分群','UMAP 和 Leiden 可从同一张邻居图分别运行。'],
    ['任务结果','对象、图表和运行记录','核对分群和运行参数，把选定结果交给注释人员。']
  ];
  const rows=routes.map(([input,output,note],i)=>'<li><button type="button" data-act="guide-jump" data-index="'+(i+1)+'" '+(S.step===i+1?'aria-current="step"':'')+'><strong>'+e(steps[i+1][0])+'</strong><span>'+e(input)+' → '+e(output)+'</span><small>'+e(note)+'</small></button></li>').join('');
  modalShow('从测序文件到待注释对象','<p class="meta">按已有数据选择起点，点击工作位可进入对应步骤。</p><ol class="guide-route">'+rows+'</ol>','guide');
}
document.addEventListener('toggle',ev=>{
  if(ev.target.matches?.('details[data-guide-step]')&&ev.target.isConnected)guideState.set(Number(ev.target.dataset.guideStep),ev.target.open);
},true);

