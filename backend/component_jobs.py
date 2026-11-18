"""Run one Scanpy stage against a frozen workbench parent. Reuse the production kernels."""
from pathlib import Path
from functools import lru_cache

from .ports import artifact
from .workspace import read_json


def input_slots(module, keys, cfg):
    raw = "layers/counts" if "layers/counts" in keys else "X"
    rep = "obsm/X_pca_harmony" if "obsm/X_pca_harmony" in keys else "obsm/X_pca"
    if module == "features":
        slots = {"merged": raw}
        if cfg.get("analysis_layer") == "soupx":
            slots["aligned_corrected"] = "layers/soupx"
        return slots
    if module == "pca":
        return {"expression": "X", "hvg": "var/highly_variable"}
    if module == "graph":
        from .advanced import graph_representation
        return {"representation":"obsm/"+graph_representation(rep.split("/")[-1],cfg)}
    return {"graph": "obsp/connectivities"}


def validate_slots(source,module,params,external=False):
    import h5py
    with h5py.File(source,"r") as f:
        return checked_slots(f,source,module,params,external)


def checked_slots(f,source,module,params,external):
    if "obs" not in f or "var" not in f:raise ValueError("H5AD 缺少 obs 或 var")
    slots=input_slots(module,f,params)
    needed=list(slots.values())
    if module == "umap":
        needed.extend(["uns/neighbors/params","obsp/distances"])
        for field,key in (("connectivities_key","connectivities"),("distances_key","distances")):
            path="uns/neighbors/"+field
            if path in f and f[path].asstr()[()]!=key:
                raise ValueError("此入口使用 Scanpy 标准近邻图，请选择 connectivities 和 distances 对应的图")
    if module=="features" and "layers/counts" not in f:
        if ("uns/log1p" in f or (not external and source.name!="qc.h5ad")):
            raise ValueError("来源对象缺少可验证的整数计数层")
    if external and module=="pca" and params.get("integration")=="harmony":needed.extend(["obs/batch","obs/condition"])
    if external and module=="features" and params.get("batch_hvg"):needed.append("obs/batch")
    missing=[s for s in needed if s not in f]
    if missing:raise ValueError("来源对象缺少所选模块需要的字段："+"、".join(missing))
    return slots


@lru_cache(maxsize=1024)
def supported_modules(source, modified):
    """Reuse immutable job output headers across status polls."""
    import h5py
    from .ports import SINGLE_MODULES
    result=[]
    try:
        with h5py.File(source,"r") as handle:
            for name in SINGLE_MODULES:
                try:checked_slots(handle,source,name,{},False)
                except (ValueError,KeyError):continue
                result.append(name)
    except OSError:pass
    return result


def resolve_source(store, project, spec):
    import hashlib
    from .workspace import child

    if spec.get("external_h5ad"):
        if spec.get("parent_job"):raise ValueError("请选择外部 H5AD 或父任务中的一项")
        source=Path(spec["external_h5ad"]).resolve(strict=True)
        if not source.is_file() or source.suffix.lower()!=".h5ad":raise ValueError("请选择 H5AD 文件")
        slots=validate_slots(source,spec["action"],spec["params"],external=True)
        with source.open("rb") as stream:digest=hashlib.file_digest(stream,"sha256").hexdigest()
        spec.update(libraries=[],source_h5ad=str(source),source_sha256=digest,source_slots=slots)
        return
    parent = store.job(spec.get("parent_job"))
    if parent["project"] != project["id"] or parent["state"] != "succeeded":
        raise ValueError("请选择当前项目中已成功完成的来源任务")
    folder = child(project["path"], parent["output"])
    source = next((folder / n for n in ("component.h5ad", "analysis.h5ad", "qc.h5ad") if (folder / n).is_file()), None)
    if source is None:
        raise ValueError("来源任务没有可复用的 H5AD 交接对象")
    slots=validate_slots(source,spec["action"],spec["params"])
    receipt = read_json(folder / "receipt.json")
    match = next((r for r in receipt["outputs"] if Path(r["path"]).name == source.name), None)
    if match is None:
        raise ValueError("父任务收据没有记录交接对象的校验值")
    spec.update(libraries=[], source_h5ad=str(source), source_sha256=match["sha256"],
                source_slots=slots, reference=read_json(folder / "parameters.json")["reference"])


def discard_dependents(obj, module):
    """Invalidation follows the graph. UMAP and Leiden are siblings."""
    if module in ("features", "pca", "graph", "leiden"):
        for k in list(obj.obs):
            if k == "leiden" or k.startswith("leiden_"):
                del obj.obs[k]
                obj.uns.pop(k, None)
        obj.uns.get("workbench", {}).pop("selected_resolution", None)
    if module in ("features", "pca", "graph", "umap"):
        obj.obsm.pop("X_umap", None)
        obj.uns.pop("umap", None)
    if module in ("features", "pca", "graph"):
        obj.uns.pop("neighbors", None)
        for k in ("connectivities", "distances"):
            obj.obsp.pop(k, None)
    if module in ("features", "pca"):
        for k in ("X_pca", "X_pca_harmony"):
            obj.obsm.pop(k, None)
        obj.varm.pop("PCs", None)
        obj.uns.pop("pca", None)
    if module == "features":
        obj.uns.pop("log1p", None)
        for k in ("highly_variable", "means", "dispersions_norm", "variances_norm", "highly_variable_nbatches"):
            if k in obj.var:
                del obj.var[k]
    obj.uns.pop("workbench_checkpoint", None)


def run_component(spec, out):
    import anndata as ad
    import numpy as np
    from scipy.sparse.csgraph import connected_components
    from .advanced import prepare_features, build_representation, build_graph, embed_graph, cluster_partitions, label_key
    from .analysis import _json
    from .qc import parameters

    source = Path(spec["source_h5ad"])
    module = spec["action"]
    dest = out / "component.h5ad"
    cfg = parameters(spec["params"])
    slots = spec["source_slots"]
    obj = ad.read_h5ad(source)
    warnings = []
    if spec.get("external_h5ad"):
        from scipy import sparse
        if not obj.obs_names.is_unique or not obj.var_names.is_unique:raise ValueError("输入对象的细胞和基因标识必须唯一")
        if "sample" not in obj.obs:obj.obs["sample"]="未登记"
        if module=="features":
            raw=obj.layers["counts"] if slots["merged"]=="layers/counts" else obj.X
            raw=sparse.csr_matrix(raw)
            if not np.isfinite(raw.data).all() or (raw.data<0).any() or (raw.data!=np.floor(raw.data)).any():
                raise ValueError("特征计算入口需要有限、非负的整数 UMI")
            if slots["merged"]=="layers/counts":obj.layers["counts"]=raw
            else:obj.X=raw
            if "soupx" in obj.layers:obj.layers["soupx"]=sparse.csr_matrix(obj.layers["soupx"])
        if module=="pca" and obj.var["highly_variable"].dtype!=bool:raise ValueError("highly_variable 须为布尔掩码")
        if module in ("umap","leiden"):
            for key in (("connectivities","distances") if module=="umap" else ("connectivities",)):
                matrix=obj.obsp[key]
                data=matrix.data if sparse.issparse(matrix) else np.asarray(matrix)
                if not np.isfinite(data).all() or (data<0).any():raise ValueError("邻居图权重和距离须为有限非负数")
            obj.obsp["connectivities"]=sparse.csr_matrix(obj.obsp["connectivities"])
            if not np.any(obj.obsp["connectivities"].data):raise ValueError("邻居图缺少有效连边")
    discard_dependents(obj, module)
    def member(key):
        return [artifact(dest, key)]
    if module == "features":
        if slots["merged"] == "layers/counts":
            obj.X = obj.layers["counts"].copy()
        selected, method, layer = prepare_features(obj, cfg)
        methods = dict(hvg=int(selected.sum()), hvg_method=method, analysis_layer=layer)
        obj.uns.setdefault("workbench", {})["analysis_layer"] = layer
        outputs = {"expression": member("X"), "hvg": member("var/highly_variable")}
    elif module == "pca":
        rep, pcs, integration = build_representation(obj, cfg, out, obj.var.highly_variable.to_numpy(), warnings)
        methods = dict(representation=rep, pca_components=pcs, integration=integration)
        outputs = {"pca": member("obsm/X_pca"), "representation": member("obsm/"+rep),
                   "variance": [artifact(out/"pca_variance.tsv")]}
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6.6,3.8))
        ax.plot(np.arange(1,pcs+1),100*obj.uns["pca"]["variance_ratio"],marker=".",color="#237f67")
        ax.set(xlabel="Principal component", ylabel="Explained variance (%)")
        fig.tight_layout()
        for ext in ("svg","png"):
            fig.savefig(out/("pca."+ext))
        plt.close(fig)
    elif module == "graph":
        neighbors = build_graph(obj, cfg, slots["representation"].split("/")[-1])
        methods = dict(neighbors=neighbors, graph_components=int(connected_components(obj.obsp["connectivities"], directed=False)[0]))
        outputs = {"graph": member("obsp/connectivities"), "distances": member("obsp/distances")}
    elif module == "umap":
        embed_graph(obj, cfg)
        methods = dict(min_dist=cfg["min_dist"], seed=cfg["seed"])
        outputs = {"embedding": member("obsm/X_umap")}
    else:
        main, comparison = cluster_partitions(obj, cfg, out, adjacency=obj.obsp["connectivities"])
        methods = dict(selected_resolution=main, stability=comparison)
        obj.uns.setdefault("workbench", {})["selected_resolution"] = main
        outputs = {"labels": [artifact(dest, "obs/"+k) for k in ["leiden", "leiden_seed_check", *(label_key(r) for r in cfg["resolutions"])]],
                   "comparison": [artifact(out/f) for f in ("cluster_comparison.tsv", "cluster_membership_overlap.tsv", "cluster_samples.tsv")]}
    if "X_umap" in obj.obsm:
        cells = obj.obs.copy()
        cells["UMAP1"], cells["UMAP2"] = obj.obsm["X_umap"].T
        cells.to_csv(out/"cells.tsv", sep="\t", index_label="cell_id")
    obj.uns["component_source"] = {"module": module, "parent_job": spec.get("parent_job") or "", "path": str(source), "sha256": spec["source_sha256"]}
    obj.write_h5ad(dest, compression="gzip")
    back = ad.read_h5ad(dest, backed="r")
    try:
        if not back.obs_names.equals(obj.obs_names) or not back.var_names.equals(obj.var_names):
            raise ValueError("模块交接对象的细胞或基因轴回读不一致")
    finally:
        back.file.close()
    _json(out/"summary.json", {"module": module, "parent_job": spec["parent_job"], "methods": methods, "warnings": warnings,
                               "cells":obj.n_obs, "genes":obj.n_vars, "readback_verified":True,
                               "stage":{"inputs":{k:[artifact(source,s)] for k,s in slots.items()}, "outputs":outputs}})

