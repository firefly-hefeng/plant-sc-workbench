"""Versioned scientific block catalog, input-aware recipe and execution trace."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict,dataclass
from datetime import datetime, timezone
from functools import wraps
import json
import time
from .ports import module_definition, contract, SINGLE_MODULES

@dataclass(frozen=True)
class Block:
    id:str
    title:str
    engine:str
    consumes:str
    produces:str
    settings:tuple=()

BLOCKS=[
    Block("reads","测序质量","FastQC / MultiQC","成对 FASTQ","测序质量报告",("threads",)),
    Block("reference","参考索引构建","Cell Ranger mkref","同版本 FASTA、GTF","可复用的参考索引",("ref_name","threads","memory_gb")),
    Block("quantify","比对与 UMI 定量","Cell Ranger count","FASTQ、参考索引","原始及已过滤液滴计数",("quantifier","chemistry","include_introns","threads","memory_gb","star_index","reference_dir","whitelist")),
    Block("call","有效条码识别","DropletUtils emptyDrops","未过滤液滴计数","候选细胞与 FDR",("lower","fdr","seed")),
    Block("ambient","环境 RNA 估计与校正","SoupX","背景液滴、候选计数与粗聚类","校正层、污染估计",("ambient_mode","analysis_layer")),
    Block("qc","质控、双细胞与筛选","SciPy / Scanpy Scrublet","候选原始 UMI 与参考集","逐条码指标、保留名单",("min_counts","min_genes","mad_multiplier","max_mito_pct","max_plastid_pct","doublet_mode","expected_doublet_rate")),
    Block("merge","对齐文库基因轴","AnnData","逐捕获 QC 对象","同轴细胞集、计数损失表",("feature_join",)),
    Block("features","归一化与特征选择","Scanpy","选定的细胞及计数层","对数表达与 HVG 掩码",("hvg_method","hvg","analysis_layer","target_sum","batch_hvg","min_cells_per_gene")),
    Block("pca","主成分与批次诊断","Scanpy PCA / Harmony","表达与特征掩码","PCA 或批次校正表示",("n_pcs","integration","seed")),
    Block("graph","近邻图","Scanpy neighbors","选定的主成分表示","稀疏近邻图",("n_neighbors","seed","graph_representation")),
    Block("umap","二维嵌入","Scanpy UMAP","近邻图","UMAP 坐标",("min_dist","seed")),
    Block("leiden","分区与稳定性比较","igraph Leiden / scikit-learn","近邻图","分区、成员重叠、ARI",("resolutions","selected_resolution","seed")),
    Block("export","图、表与交接对象","AnnData / Matplotlib","计数、表示、图与分区","H5AD、图表、回读记录")
]
INDEX={b.id:b for b in BLOCKS}
def recipe(spec,tools,*,requires_call=False):
    libs=spec["libraries"];cfg=spec["params"];a=spec["action"];out=[]
    fast=any(l.get("kind")=="fastq" for l in libs)
    call=(requires_call or cfg["cell_calling"]=="emptydrops" or any(l.get("kind")=="raw" and not l.get("filtered_path") for l in libs))
    use={"analysis":{"qc","merge","features","pca","graph","umap","leiden","export"},
         "quality":{"qc","merge","export"},"from_qc":{"features","pca","graph","umap","leiden","export"},
         "recluster":{"leiden","export"},"quantify":{"quantify"},"read_qc":{"reads"},"build_reference":{"reference"},**{m:{m} for m in SINGLE_MODULES}}[a].copy()
    if fast and a in ("analysis","quality"):use.add("quantify")
    if fast and cfg.get("run_read_qc") and a in ("analysis","quality","quantify"):use.add("reads")
    if a in ("analysis","quality") and (call or (fast and cfg["cell_calling"]=="emptydrops")):use.add("call")
    if a in ("analysis","quality") and cfg["ambient_mode"]=="soupx":use.add("ambient")
    required={"reads":("fastqc","multiqc"),"reference":("cellranger",),"quantify":("cellranger",),"call":("emptydrops",),"ambient":("soupx",)}
    use.add("export")
    for b in BLOCKS:
        if b.id not in use:continue
        engine=b.engine
        needs=required.get(b.id,())
        star=b.id in ("reference","quantify") and cfg.get("quantifier")=="starsolo"
        if star:needs=("starsolo",);engine="STARsolo 2.7.11b"
        missing=[name for name in needs if not tools.get(name,{}).get("available")]
        issues=["缺少 "+x for x in missing]
        if b.id=="quantify" and not star and cfg["chemistry"]=="SC3Pv3_10":issues.append("短 UMI 布局需要选择 STARsolo")
        if b.id=="quantify" and not star and not cfg.get("reference_dir"):issues.append("请选择已构建的 Cell Ranger 参考索引")
        if b.id=="quantify" and star and not cfg.get("star_index") and (
            spec["reference"].get("id")!="ath-tair10-62" or not tools.get("starsolo",{}).get("tair10_index")):
            issues.append("请选择与本捕获匹配的 STAR 索引；拟南芥 TAIR10 可选内置版本。")
        if b.id=="call" and cfg["cell_calling"]=="emptydrops":
            missing_raw=[l["id"] for l in libs if l.get("kind") not in ("raw","fastq") and not l.get("raw_path")]
            if missing_raw:issues.append("重新判定条码需要背景液滴："+"、".join(missing_raw))
        if b.id=="ambient":
            missing_raw=[l["id"] for l in libs if l.get("kind") not in ("raw","fastq") and not l.get("raw_path")]
            if missing_raw:issues.append("以下捕获需要匹配的原始液滴矩阵："+"、".join(missing_raw))
        if b.id=="reference" and not (cfg.get("fasta") and cfg.get("gtf")):issues.append("需要 FASTA 和 GTF")
        out.append({**asdict(b),**module_definition(b.id),"engine":engine,"version":1,"state":"blocked" if issues else "ready","issues":issues,
                    "parameters":{k:cfg[k] for k in b.settings if k in cfg}})
    return {"schema":"plant-workflow/1","action":a,"ports":contract(a,True),"blocks":out,"ready":all(x["state"]=="ready" for x in out)}

_trace=ContextVar("plant_workflow_trace",default=None)
def trace_to(file):_trace.set(file)
def event(block,state,**fields):
    target=_trace.get()
    if target:
        with target.open("a",encoding="utf-8") as f:
            f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"block":block,"state":state,**fields},ensure_ascii=False)+"\n")
@contextmanager
def step(block):
    start=time.monotonic();event(block,"started")
    try:yield
    except Exception as ex:
        event(block,"failed",message=str(ex),seconds=round(time.monotonic()-start,3));raise
    else:event(block,"completed",seconds=round(time.monotonic()-start,3))
def block(name):
    if name not in INDEX:raise KeyError(name)
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            with step(name):return fn(*args,**kwargs)
        return wrapped
    return decorate

