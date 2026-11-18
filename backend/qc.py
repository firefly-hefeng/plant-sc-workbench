"""Read UMI data and apply auditable, per-capture QC in the original feature space."""
from __future__ import annotations

import gzip
import math
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import io, sparse


DEFAULTS = {
    "min_counts": 1, "min_genes": 1, "mad_multiplier": 4.0,
    "max_mito_pct": None, "max_plastid_pct": None,
    "doublet_mode": "report", "expected_doublet_rate": 0.05,
    "hvg": 2000, "n_pcs": 30, "n_neighbors": 15,
    "resolutions": [0.5, 1.0], "seed": 42, "integration": "none",
    "feature_join": "strict", "target_sum": 10000, "min_dist": 0.5,
}


def parameters(overrides=None):
    cfg = {**DEFAULTS, **(overrides or {})}
    for key, low, high in (
        ("min_counts", 0, 2**31-1), ("min_genes", 0, 2**31-1), ("hvg", 3, 100000),
        ("n_pcs", 2, 500), ("n_neighbors", 2, 1000), ("seed", 0, 2**31-1),
    ):
        x = float(cfg[key])
        if not x.is_integer() or not low <= x <= high:
            raise ValueError(f"{key} 须为 {low} 至 {high} 的整数")
        cfg[key] = int(x)
    for key, low, high in (
        ("mad_multiplier", 0, 100), ("max_mito_pct", 0, 100), ("max_plastid_pct", 0, 100),
        ("expected_doublet_rate", 0.00001, .49999), ("target_sum", 1, 1e9), ("min_dist", 0, 1),
    ):
        if cfg[key] is None and key in {"max_mito_pct", "max_plastid_pct"}:
            continue
        x = float(cfg[key])
        if not math.isfinite(x) or not low <= x <= high:
            raise ValueError(f"{key} 须为 {low} 至 {high} 的数值")
        cfg[key] = x
    for key, allowed in (("doublet_mode", {"off", "report", "remove"}),
                         ("feature_join", {"strict", "intersection"}),
                         ("integration", {"none", "harmony"})):
        if cfg[key] not in allowed:
            raise ValueError(f"{key} 须选择 {', '.join(sorted(allowed))}")
    resolutions = cfg["resolutions"]
    if isinstance(resolutions, str):
        resolutions = resolutions.replace("，", ",").split(",")
    if not isinstance(resolutions, (tuple, list)):
        resolutions = [resolutions]
    cfg["resolutions"] = list(dict.fromkeys(float(r) for r in resolutions))
    if not 1 <= len(cfg["resolutions"]) <= 16 or any(not 0 < r <= 100 for r in cfg["resolutions"]):
        raise ValueError("请提供 1 至 16 个大于 0 且不超过 100 的分辨率")
    return cfg


def mex_file(directory, names):
    for name in names:
        for suffix in ("", ".gz"):
            path = directory / (name + suffix)
            if path.is_file():
                return path
    raise ValueError(f"{directory} 缺少 {' / '.join(names)}")


def source_files(path):
    path = Path(path)
    if path.is_dir():
        return [mex_file(path, group) for group in (["matrix.mtx"], ["features.tsv", "genes.tsv"], ["barcodes.tsv"])]
    if not path.is_file():
        raise ValueError(f"找不到矩阵 {path}")
    return [path]


def count_layer_name(selection, available):
    if selection in ("", None):
        return "counts" if "counts" in available else None
    return None if selection == "X" else selection


def read_counts(path, counts_layer=None, *, corrected=False):
    path = Path(path)
    if path.is_dir():
        matrix, features, barcodes = source_files(path)
        f = pd.read_csv(features, sep="\t", header=None, dtype=str, keep_default_na=False)
        b = pd.read_csv(barcodes, sep="\t", header=None, dtype=str, keep_default_na=False)
        with (gzip.open if matrix.suffix == ".gz" else open)(matrix, "rb") as stream:
            raw = sparse.csr_matrix(io.mmread(stream).T)
        if raw.shape != (len(b), len(f)):
            raise ValueError("MEX 行列数须与基因、条码数一致（文件为基因 × 条码）")
        include = f.iloc[:, 2].eq("Gene Expression").to_numpy() if f.shape[1] >= 3 else np.ones(len(f), bool)
        var = pd.DataFrame(index=pd.Index(f.loc[include, 0].values, name="gene_id"))
        if f.shape[1] >= 2:
            var["gene_symbol"] = f.loc[include, 1].values
        barcodes = pd.Index(b.iloc[:, 0].values)
        raw = raw[:, include]
    else:
        if path.suffix.lower() == ".h5ad":
            obj = ad.read_h5ad(path)
            if "capture" in obj.obs and obj.obs["capture"].nunique(dropna=False) > 1:
                raise ValueError("H5AD 内含多个物理捕获，请用工作台 split_captures 按 obs.capture 拆分后分别登记")
            layer = count_layer_name(counts_layer, obj.layers)
            if layer and layer not in obj.layers:
                raise ValueError(f"文件缺少已选择的计数层 {layer}")
            matrix = obj.layers[layer] if layer else obj.X
            if layer is None and "log1p" in obj.uns:
                raise ValueError("X 带有 log1p 元数据。请选择有明确来源的原始计数层")
        elif path.suffix.lower() in {".h5", ".hdf5"}:
            import scanpy as sc
            obj = sc.read_10x_h5(path, gex_only=True)
            matrix = obj.X
        else:
            raise ValueError("支持 10x MEX 目录、10x H5 或 H5AD 计数文件")
        var = obj.var.copy()
        barcodes = obj.obs_names.astype(str)
        if "gene_ids" in var:
            var["gene_symbol"] = obj.var_names.astype(str)
            var.index = pd.Index(var["gene_ids"].astype(str), name="gene_id")
        include = var["feature_types"].eq("Gene Expression").to_numpy() if "feature_types" in var else np.ones(len(var), bool)
        raw = sparse.csr_matrix(matrix)[:, include]
        var = var.iloc[np.flatnonzero(include)].copy()
    if not len(var) or not len(barcodes):
        raise ValueError("所选矩阵没有基因表达条目或条码")
    if not var.index.is_unique or not barcodes.is_unique or (var.index == "").any() or (barcodes == "").any():
        raise ValueError("同一文库中的基因 ID 与条码必须非空且唯一")
    if not np.isfinite(raw.data).all() or (raw.data < 0).any() or (raw.data > 2**31-1).any() or (not corrected and (raw.data != np.floor(raw.data)).any()):
        raise ValueError("输入须为非负、有限的整数 UMI 计数。请检查 counts_layer；不会将小数取整")
    raw = raw.astype(np.float32 if corrected else np.int64)
    raw.sum_duplicates()
    raw.eliminate_zeros()
    return ad.AnnData(raw, obs=pd.DataFrame(index=barcodes), var=var)


def organelle_sets(reference):
    sets = (reference or {}).get("sets", {})
    return {
        "mito": set(sets.get("mitochondria", sets.get("mitochondrial", sets.get("mito", [])))),
        "plastid": set(sets.get("plastid", sets.get("chloroplast", []))),
    }


def capture_metrics(obj, reference):
    metrics = pd.DataFrame(index=obj.obs_names.copy())
    counts = obj.X
    total = np.asarray(counts.sum(axis=1)).ravel()
    metrics["total_counts"] = total
    metrics["n_genes"] = counts.getnnz(axis=1)
    metrics["top1_gene_pct"] = 100 * counts.max(axis=1).toarray().ravel() / np.where(total > 0, total, np.nan)
    matches = {}
    for key, genes in organelle_sets(reference).items():
        selector = obj.var_names.isin(genes)
        matches[key] = {"genes_in_set": len(genes), "genes_measured": int(selector.sum())}
        metrics[f"{key}_pct"] = np.nan
        if selector.any():
            numerator = np.asarray(counts[:, selector].sum(axis=1)).ravel()
            metrics[f"{key}_pct"] = 100 * numerator / np.where(total > 0, total, np.nan)
    return metrics, matches


def screen(metrics, cfg):
    reasons = {"empty": metrics.total_counts.eq(0), "low_counts": metrics.total_counts < cfg["min_counts"],
               "low_genes": metrics.n_genes < cfg["min_genes"]}
    thresholds = {}
    for col in ("total_counts", "n_genes"):
        vals = np.log1p(metrics[col].to_numpy())
        center = np.median(vals)
        mad = np.median(np.abs(vals-center))
        if len(vals) >= 20 and mad > 0 and cfg["mad_multiplier"] > 0:
            lower = center - 1.4826 * cfg["mad_multiplier"] * mad
            thresholds[col] = float(max(0, np.expm1(lower)))
            reasons["low_" + col + "_MAD"] = vals < lower
        else:
            thresholds[col] = None
    for short in ("mito", "plastid"):
        limit = cfg["max_" + short + "_pct"]
        if limit is not None:
            col = metrics[short + "_pct"]
            if not col.notna().any():
                raise ValueError(f"已设置 {short} 阈值，但当前文库缺少匹配的参考基因")
            reasons["high_" + short] = col > limit
    return pd.DataFrame(reasons, index=metrics.index), thresholds


def doublets(obj, metrics, eligible, cfg):
    metrics["doublet_score"] = np.nan
    metrics["predicted_doublet"] = False
    if cfg["doublet_mode"] == "off":
        return {"status": "not_requested"}
    if eligible.sum() < 100:
        return {"status": "not_assessed", "reason": "初筛后少于 100 个条码，未作 Scrublet 判定"}
    import scanpy as sc
    sub = obj[eligible].copy()
    try:
        sc.pp.scrublet(sub, expected_doublet_rate=cfg["expected_doublet_rate"],
                       n_prin_comps=min(20, sub.n_obs - 2, sub.n_vars - 2), random_state=cfg["seed"],
                       use_approx_neighbors=False, verbose=False)
        threshold = sub.uns["scrublet"].get("threshold")
        metrics.loc[sub.obs_names, "doublet_score"] = sub.obs["doublet_score"]
        if threshold is None or not np.isfinite(threshold):
            return {"status": "scores_only", "reason": "未找到自动判定阈值"}
        metrics.loc[sub.obs_names, "predicted_doublet"] = sub.obs["predicted_doublet"].fillna(False).astype(bool)
        return {"status": "scored", "threshold": float(threshold), "eligible": int(eligible.sum()),
                "predicted": int(metrics.predicted_doublet.sum()), "mode": cfg["doublet_mode"]}
    except (ValueError, RuntimeError, IndexError, ImportError, KeyError, ZeroDivisionError) as err:
        return {"status": "not_assessed", "reason": str(err)}
