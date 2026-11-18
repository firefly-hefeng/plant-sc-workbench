"""Pre-annotation workflow shared by the GUI and harness adapter."""
from __future__ import annotations

from hashlib import file_digest
from html import escape
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import shutil
import time

import anndata as ad
import numpy as np
import pandas as pd

from .advanced import cluster_partitions, figures, reduce_and_cluster
from .blocks import block
from .qc import capture_metrics, doublets, parameters, read_counts, screen, source_files


def _json(path, value):
    def convert(x):
        if isinstance(x, Path):
            return str(x)
        if isinstance(x, np.generic):
            return x.item()
        raise TypeError(f"Unsupported value {type(x).__name__}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=convert, allow_nan=False), encoding="utf-8")


def _library_list(spec):
    libraries = spec.get("libraries") or []
    if not libraries:
        raise ValueError("请选择至少一个计数矩阵")
    ids = [str(x.get("id", "")).strip() for x in libraries]
    if any(not s or ":" in s for s in ids) or len(set(ids)) != len(ids):
        raise ValueError("每个物理捕获需要唯一非空的文库编号，编号不能包含冒号")
    paths = [Path(lib["path"]).resolve() for lib in libraries]
    if len(paths) != len(set(paths)):
        raise ValueError("同一个计数矩阵被重复登记。请逐个提交互不重复的物理捕获")
    for key in ("species", "modality", "reference_id"):
        distinct = {str(x[key]).strip() for x in libraries if x.get(key)}
        if len(distinct) > 1:
            raise ValueError(f"请按相同的 {key} 分开建图")
    if any(str(x.get("role",x.get("kind","filtered"))).lower() in {"raw","raw_matrix","raw_droplets","fastq"} for x in libraries):
        raise ValueError("原始液滴和 FASTQ 请先完成定量或有效条码调用")
    return libraries


@block("qc")
def _capture(lib, reference, cfg, *, predict):
    obj = read_counts(lib["path"], lib.get("counts_layer"))
    met, matches = capture_metrics(obj, reference)
    caps = {k:v for k,v in (lib.get("params") or {}).items() if k in
            {"min_counts","min_genes","max_mito_pct","max_plastid_pct","mad_multiplier","doublet_mode","expected_doublet_rate"}}
    cfg = parameters({**cfg, **caps})
    reasons, thresholds = screen(met, cfg)
    eligible = ~reasons.any(axis=1)
    status = doublets(obj, met, eligible.to_numpy(), cfg) if predict else {"status":"not_run_in_preview"}
    if predict and cfg["doublet_mode"] == "remove":
        if status["status"] != "scored":
            raise ValueError(f"{lib['id']} 需要可靠双细胞判定才可执行移除：{status.get('reason','未判定')}。可改为报告模式。")
        reasons["doublet"] = met.predicted_doublet
    met["retained"] = ~reasons.any(axis=1)
    reason_text=np.full(len(met),"",dtype=object)
    for key in reasons:
        hit=reasons[key].to_numpy(dtype=bool)
        reason_text[hit] = np.where(reason_text[hit]=="",key,reason_text[hit]+"|"+key)
    met["filter_reason"] = reason_text
    met["barcode"] = obj.obs_names.to_numpy()
    met["capture"] = str(lib["id"]).strip()
    for k in ("sample","condition","batch","modality"):
        met[k] = str(lib.get(k) or (lib["id"] if k=="sample" else "unspecified"))
    met.index = pd.Index([f"{str(lib['id']).strip()}:{s}" for s in obj.obs_names],name="cell_id")
    obj.obs = met.copy()
    warnings = []
    for key,info in matches.items():
        if not info["genes_measured"]:
            warnings.append(f"{lib['id']} 的 {key} 参考集合与输入基因无匹配，比例未计算")
    if not thresholds or any(v is None for v in thresholds.values()):
        warnings.append(f"{lib['id']} 部分 MAD 阈值未启用或数据量/离散度不足")
    if status["status"]=="scored" and status["eligible"]:
        fraction=status["predicted"]/status["eligible"]
        status["predicted_fraction"]=float(fraction)
        if fraction>max(0.25,3*cfg["expected_doublet_rate"]):
            warnings.append(f"{lib['id']} 的 Scrublet 将 {fraction:.1%} 的候选条码标为双细胞，远高于设定的预期率 {cfg['expected_doublet_rate']:.1%}。请结合测序深度、上样量和分数分布复核。")
    if status["status"] in {"not_assessed","scores_only"}:
        warnings.append(f"{lib['id']} 双细胞：{status.get('reason')}")
    record = {"id":str(lib["id"]),"sample":str(met["sample"].iloc[0]),"input_cells":obj.n_obs,
              "retained_cells":int(met.retained.sum()), "median_counts":float(met.total_counts.median()),
              "median_genes":float(met.n_genes.median()),"matched_genes":matches,
              "mad_thresholds":thresholds,"doublets":status,"input_genes":obj.n_vars,
              "rule_counts":{k:int(v) for k,v in reasons.sum().items()},
              "multiple_rules":int((reasons.sum(axis=1)>1).sum())}
    return obj, record, warnings


def preview_qc(spec):
    cfg=parameters(spec.get("params"))
    records, warnings=[],[]
    for lib in _library_list(spec):
        obj,record,notes=_capture(lib,spec.get("reference",{}),cfg,predict=False)
        q=obj.obs
        n=min(250,len(q))
        points=q.iloc[np.linspace(0,len(q)-1,n,dtype=int)]
        record["preview_points"] = points[["total_counts","n_genes","retained"]].values.tolist()
        records.append(record)
        warnings.extend(notes)
    return {"input_cells":sum(x["input_cells"] for x in records),
            "retained_cells":sum(x["retained_cells"] for x in records),"libraries":records,
            "warnings":warnings,"stage":"before_doublets"}


def _hash(path):
    with Path(path).open("rb") as f:
        return file_digest(f,"sha256").hexdigest()


def _load_correction(lib, obj):
    derived = read_counts(lib["corrected_path"], lib.get("corrected_counts_layer"), corrected=True)
    barcodes = pd.Index(obj.obs.barcode)
    if set(derived.obs_names)!=set(barcodes) or set(derived.var_names)!=set(obj.var_names):
        raise ValueError("SoupX 校正层的条码或基因与原始计数不匹配")
    obj.layers["soupx"] = derived[barcodes,obj.var_names].X.copy()


@block("merge")
def _merge(objects, records, cfg):
    genes=objects[0].var_names
    for obj in objects[1:]:
        if cfg["feature_join"]=="strict" and (len(genes)!=obj.n_vars or not genes.isin(obj.var_names).all()):
            raise ValueError("捕获之间的基因集合不同。请核对相同参考，或明确选择交集模式")
        genes=genes.intersection(obj.var_names,sort=False)
    if len(genes)<3:
        raise ValueError("各文库共享基因太少")
    selected=[]
    for obj, record in zip(objects,records):
        native=obj.obs.total_counts.to_numpy()
        shared=obj[:,genes].copy()
        counts=np.asarray(shared.X.sum(axis=1)).ravel()
        obj.obs["feature_join_removed_counts"] = native-counts
        empty = obj.obs.retained.to_numpy() & (counts==0)
        obj.obs.loc[empty,"filter_reason"]="no_counts_on_shared_features"
        obj.obs.loc[empty,"retained"]=False
        record.update(retained_cells=int(obj.obs.retained.sum()),shared_genes=len(genes),
                      discarded_counts_from_feature_join=int((native-counts).sum()),
                      empty_after_feature_join=int(empty.sum()))
        shared.obs=obj.obs.copy()
        if shared.obs.retained.any():
            selected.append(shared[shared.obs.retained].copy())
    if not selected:
        raise ValueError("所有条码均被过滤，请复核阈值和基因参考")
    obj=ad.concat(selected,join="inner",merge="first")
    return obj,pd.concat([o.obs for o in objects])


def _report(out, summary):
    h = escape
    rows="".join(f"<tr><td>{h(str(x['id']))}</td><td>{x['input_cells']:,}</td><td>{x['retained_cells']:,}</td>"
                 f"<td>{x['median_counts']:,.0f}</td><td>{x['median_genes']:,.0f}</td></tr>" for x in summary["libraries"])
    notes="".join("<li>"+h(str(v))+"</li>" for v in summary["warnings"])
    html=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>注释前分析报告</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;max-width:1000px;margin:2em auto;padding:0 20px;color:#203a32}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%}}td,th{{padding:.4em;text-align:left;border-bottom:1px solid #ccd8d1}}p{{line-height:1.6}}</style>
<h1>植物单细胞注释前分析</h1><p>共有 {summary['input_cells']:,} 个候选条码，保留 {summary['retained_cells']:,} 个，{summary['genes']:,} 个共有基因，主分区得到 {summary['clusters']} 个簇。</p>
<h2>分捕获质控</h2><table><thead><tr><th>捕获</th><th>输入条码</th><th>保留条码</th><th>UMI 中位数</th><th>检出基因中位数</th></tr></thead><tbody>{rows}</tbody></table>
<img src="qc.png" alt="逐条码质控与各捕获保留数"><h2>聚类与样本构成</h2><img src="embedding.png" alt="UMAP 聚类和捕获分布"><p>图中细胞多于五万时显示随机抽样。完整坐标和分区见 cells.tsv；聚类稳定性及成员重叠见 cluster_comparison.tsv 和 cluster_membership_overlap.tsv。</p>
<h2>复核事项</h2><ul>{notes}</ul><p>交接对象 analysis.h5ad 含完整分析基因轴、原始计数层、特征选择、PCA、UMAP、邻居图和分区。身份判定由后续注释人员完成。</p></html>"""
    (out/"report.html").write_text(html,encoding="utf-8")


def _quality_data(spec,cfg,reference,out,progress):
    libs=_library_list(spec)
    objects,records,warnings,inputs=[],[],[],[]
    progress(8,"读取原始计数并按物理捕获检查质量")
    for i,lib in enumerate(libs):
        obj,rec,notes=_capture(lib,reference,cfg,predict=True)
        capture_dir=out/"captures"/f"{i+1:03d}"
        capture_dir.mkdir(parents=True,exist_ok=True)
        if lib.get("corrected_path"):
            _load_correction(lib,obj)
        for key in ("path","corrected_path"):
            if lib.get(key):
                for p in source_files(lib[key]):
                    inputs.append({"capture":lib["id"],"role":key,"path":str(p.absolute()),
                                   "bytes":p.stat().st_size,"sha256":_hash(p)})
        objects.append(obj);records.append(rec);warnings.extend(notes)
        progress(15+int(28*(i+1)/len(libs)),f"已完成捕获 {lib['id']} 的质量检查")
    if any("soupx" in obj.layers for obj in objects) and not all("soupx" in obj.layers for obj in objects):
        raise ValueError("需为每个捕获提供匹配的校正层，或分开分析")
    obj,qc=_merge(objects,records,cfg)
    for i, capture in enumerate(objects, 1):
        capture.obs.to_csv(out/"captures"/f"{i:03d}"/"qc.tsv", sep="\t", index_label="cell_id")
    del objects
    qc.to_csv(out/"qc_cells.tsv",sep="\t",index_label="cell_id")
    simple=pd.DataFrame([{k:v for k,v in row.items() if not isinstance(v,dict)} for row in records])
    simple.insert(0,"plot_id",["L"+str(i+1) for i in simple.id.rank(method="first").astype(int)-1])
    simple.to_csv(out/"qc_libraries.tsv",sep="\t",index=False)
    return obj,qc,records,warnings,inputs


def _load_checkpoint(spec,out):
    source=Path(spec["checkpoint_h5ad"])
    receipt=json.loads((source.parent/"receipt.json").read_text(encoding="utf-8"))
    digest=_hash(source)
    if not any(row["sha256"]==digest and Path(row["path"]).name=="qc.h5ad" for row in receipt["outputs"]):
        raise ValueError("质控对象的校验值与来源任务回执不一致")
    obj=ad.read_h5ad(source)
    if obj.uns.get("workbench_checkpoint",{}).get("type")!="quality":
        raise ValueError("需要由质控与清洗工作位导出的对象")
    info=json.loads((source.parent/"summary.json").read_text(encoding="utf-8"))
    for name in ("qc_cells.tsv","qc_libraries.tsv"):
        shutil.copyfile(source.parent/name,out/name)
    qc=pd.read_csv(out/"qc_cells.tsv",sep="\t",index_col=0)
    return obj,qc,info["libraries"],list(info["warnings"]),[{"role":"quality_checkpoint","path":str(source),"sha256":digest}]


def run_analysis(spec, outdir, progress=None):
    start=time.monotonic()
    progress=progress or (lambda percent,message:None)
    out=Path(outdir)
    out.mkdir(parents=True,exist_ok=True)
    if (out/"summary.json").exists() or (out/"analysis.h5ad").exists():
        raise ValueError("请选择新的运行目录，以免覆盖历史结果")
    cfg=parameters(spec.get("params"))
    reference=spec.get("reference") or {}
    action=spec.get("action","analysis")
    if action=="from_qc":
        obj,qc,records,warnings,inputs=_load_checkpoint(spec,out)
    else:
        obj,qc,records,warnings,inputs=_quality_data(spec,cfg,reference,out,progress)
    if action=="quality":
        checkpoint=out/"qc.h5ad"
        obj.uns["workbench_checkpoint"]={"type":"quality","version":1,"reference_id":reference.get("id","none")}
        obj.write_h5ad(checkpoint,compression="gzip")
        back=ad.read_h5ad(checkpoint)
        if not back.obs_names.equals(obj.obs_names) or not back.var_names.equals(obj.var_names) or (back.X!=obj.X).nnz:
            raise RuntimeError("质控交接对象回读失败")
        figures(None,qc,out)
        result=dict(action=action,input_cells=len(qc),retained_cells=obj.n_obs,genes=obj.n_vars,
                    libraries=records,warnings=warnings,readback_verified=True)
        _json(out/"summary.json",result)
        _json(out/"input_manifest.json",inputs)
        return result
    progress(49,"归一化、选择分析特征并计算主成分")
    methods=reduce_and_cluster(obj,cfg,out,progress,warnings)
    cells=obj.obs.copy()
    cells["UMAP1"]=obj.obsm["X_umap"][:,0];cells["UMAP2"]=obj.obsm["X_umap"][:,1]
    cells.to_csv(out/"cells.tsv",sep="\t",index_label="cell_id")
    progress(82,"绘制质控与嵌入图并回读分析对象")
    figures(obj,qc,out)
    obj.uns["workbench"]={"version":"1","reference_id":str(reference.get("id","custom")),
                          "selected_resolution":methods["selected_resolution"],"analysis_layer":methods["analysis_layer"]}
    obj.write_h5ad(out/"analysis.h5ad",compression="gzip")
    reopened=ad.read_h5ad(out/"analysis.h5ad")
    if (not reopened.obs_names.equals(obj.obs_names) or not reopened.var_names.equals(obj.var_names)
        or (reopened.layers["counts"] != obj.layers["counts"]).nnz
        or not reopened.obs["leiden"].equals(obj.obs["leiden"])
        or reopened.obsp["connectivities"].shape!=(obj.n_obs,obj.n_obs)):
        raise RuntimeError("H5AD 回读验证失败")
    packages={}
    for name in ("scanpy","anndata","numpy","scipy","pandas","scikit-learn","umap-learn","igraph","harmonypy","matplotlib"):
        try: packages[name]=version(name)
        except PackageNotFoundError: pass
    _json(out/"environment.json",{"python":platform.python_version(),"platform":platform.platform(),"packages":packages})
    _json(out/"analysis_spec.json",{**spec,"params":cfg})
    _json(out/"input_manifest.json",inputs)
    summary={"status":"completed","input_cells":len(qc),"retained_cells":obj.n_obs,"cells":obj.n_obs,
             "genes":obj.n_vars,"clusters":int(obj.obs.leiden.nunique()),"resolutions":cfg["resolutions"],
             "libraries":records,"methods":methods,"warnings":warnings,"readback_verified":True}
    _report(out,summary)
    summary["artifacts"]=sorted(p.name for p in out.iterdir() if p.is_file())
    summary["elapsed_seconds"]=round(time.monotonic()-start,3)
    _json(out/"summary.json",summary)
    progress(98,"分析对象和结果文件已通过回读检查")
    return summary


def recluster(graph_h5ad, outdir, resolutions, seed=42, progress=None):
    """Derive a new partition from a saved workbench graph. Never mutate its parent."""
    start=time.monotonic()
    progress=progress or (lambda percent,message:None)
    source=Path(graph_h5ad).resolve()
    out=Path(outdir).resolve()
    if out == source.parent:
        raise ValueError("重聚类需要新的结果目录")
    if (out/"summary.json").exists() or (out/"analysis.h5ad").exists():
        raise ValueError("结果目录已被使用")
    out.mkdir(parents=True,exist_ok=True)
    progress(8,"读取已保存的邻居图与坐标")
    obj=ad.read_h5ad(source)
    base=json.loads((source.parent/"summary.json").read_text(encoding="utf-8"))
    cfg=parameters({"resolutions":resolutions,"seed":seed})
    if "connectivities" not in obj.obsp or "X_umap" not in obj.obsm or "counts" not in obj.layers:
        raise ValueError("所选对象缺少工作台交接要求的邻居图、UMAP 或原始计数")
    parent_hash=_hash(source)
    progress(40,"使用父版本的邻居图计算分辨率比较")
    main,comparison=cluster_partitions(obj,cfg,out)
    obj.uns["workbench"]["selected_resolution"]=main
    obj.uns["workbench"]["parent_artifact_sha256"]=parent_hash
    for f in ("qc_cells.tsv","qc_libraries.tsv","environment.json","pca_variance.tsv","qc.png","qc.svg"):
        if (source.parent/f).is_file():
            shutil.copyfile(source.parent/f,out/f)
    qc=pd.read_csv(out/"qc_cells.tsv",sep="\t",index_col=0)
    cells=obj.obs.copy()
    cells["UMAP1"]=obj.obsm["X_umap"][:,0];cells["UMAP2"]=obj.obsm["X_umap"][:,1]
    cells.to_csv(out/"cells.tsv",sep="\t",index_label="cell_id")
    progress(76,"导出新分区，验证沿用的图与坐标")
    figures(obj,qc,out)
    obj.write_h5ad(out/"analysis.h5ad",compression="gzip")
    back=ad.read_h5ad(out/"analysis.h5ad")
    if (not back.obs_names.equals(obj.obs_names) or not np.array_equal(back.obsm["X_umap"],obj.obsm["X_umap"])
        or (back.obsp["connectivities"]!=obj.obsp["connectivities"]).nnz or not back.obs.leiden.equals(obj.obs.leiden)):
        raise RuntimeError("重聚类产物回读失败")
    _json(out/"input_manifest.json",[{"role":"parent_graph","path":str(source),"sha256":parent_hash}])
    _json(out/"analysis_spec.json",{"action":"recluster","graph_h5ad":str(source),"resolutions":cfg["resolutions"],"seed":cfg["seed"]})
    summary={**base,"status":"completed","action":"recluster","clusters":int(obj.obs.leiden.nunique()),
             "resolutions":cfg["resolutions"],"readback_verified":True,"parent_graph_sha256":parent_hash,
             "methods":{**base["methods"],"selected_resolution":main,"stability":comparison,"graph_reused":True}}
    _report(out,summary)
    summary["artifacts"]=sorted(p.name for p in out.iterdir() if p.is_file())
    summary["elapsed_seconds"]=round(time.monotonic()-start,3)
    _json(out/"summary.json",summary)
    progress(98,"分区与原始邻居图回读通过")
    return summary
