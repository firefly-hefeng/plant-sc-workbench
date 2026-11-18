"""Cluster marker annotation on workbench counts. See resources/markers for cited sources."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

PANELS = Path(__file__).resolve().parents[1] / "resources" / "markers"
RULE = dict(min_cells=10, min_support=2, min_prevalence=.15, min_delta=.10, min_score=.10, min_margin=.08)

def matching_panel(species, organ, modality, reference):
    for path in sorted(PANELS.glob("*.json")):
        panel = json.loads(path.read_text(encoding="utf-8"))
        if (species, organ, reference) == (panel["species"], panel["organ"], panel["reference"]) and modality in panel["modalities"]:
            return panel
    return None

def panel_genes(panel):
    return pd.Index(sorted({gene for markers in panel["types"].values()
                            for key in ("positive","negative") for gene in markers.get(key,[])}))

def annotate_clusters(obj, panel, method="specificity"):
    if method not in ("prevalence", "specificity"):
        raise ValueError("Unknown annotation method")
    if not obj.n_obs or not obj.var_names.is_unique or obj.obs["leiden"].isna().any():
        raise ValueError("Require unique gene IDs and complete cluster membership")
    raw = sparse.csr_matrix(obj.layers["counts"], copy=False)
    if not np.isfinite(raw.data).all() or (raw.data < 0).any() or (
            not np.issubdtype(raw.dtype,np.integer) and (np.floor(raw.data) != raw.data).any()):
        raise ValueError("Annotation requires nonnegative integer counts")
    if not panel:
        return pd.Series("unknown", index=obj.obs_names), pd.DataFrame({"reason":["unsupported_scope"]})
    genes=panel_genes(panel).intersection(obj.var_names,sort=False)
    counts=raw[:,obj.var_names.get_indexer(genes)]
    counts.sum_duplicates()
    counts.eliminate_zeros()
    position={}
    for label,markers in panel["types"].items():
        position[label]=[genes.get_indexer(genes.intersection(markers.get(key,[]),sort=False))
                         for key in ("positive","negative")]
    groups = obj.obs["leiden"].astype(str)
    total = counts.getnnz(axis=0)
    choices, evidence = {}, []
    for cluster in sorted(groups.unique()):
        mask = groups.eq(cluster).to_numpy()
        n = mask.sum()
        detected = counts[mask].getnnz(axis=0)
        inside = detected / n
        delta = inside - (total - detected) / max(1, len(groups) - n)
        rows = []
        for label, markers in panel["types"].items():
            pos, neg = position[label]
            support = int((inside[pos] >= RULE["min_prevalence"]).sum())
            score = float(inside[pos].mean()) if pos.size else 0.
            reason = "" if support else "weak_detection"
            if method == "specificity":
                support = int(((inside[pos] >= RULE["min_prevalence"]) & (delta[pos] >= RULE["min_delta"])).sum())
                score = (float(delta[pos].mean()) if pos.size else 0.) - (float(np.maximum(delta[neg], 0).mean()) if neg.size else 0.)
                criteria = [(n==len(groups), "no_comparison_cells"), (pos.size < RULE["min_support"], "marker_ids_missing"), (n < RULE["min_cells"], "small_cluster"),
                            (support < RULE["min_support"], "insufficient_supported_markers"), (score < RULE["min_score"], "weak_specificity")]
                reason = next((msg for fail, msg in criteria if fail), "")
            rows.append(dict(cluster=cluster, candidate=label, n_cells=int(n), score=score, support=support,
                             positive=",".join(genes[pos]), negative=",".join(genes[neg]),
                             reason=reason, source=markers["source"]))
        rows.sort(key=lambda r: (-r["score"], r["candidate"]))
        best = rows[0]
        margin = best["score"] - (rows[1]["score"] if len(rows)>1 else 0.)
        rejection = best["reason"] or ("competing_labels" if method=="specificity" and margin < RULE["min_margin"] else "")
        choices[cluster] = "unknown" if rejection else best["candidate"]
        evidence.extend(dict(row, top_margin=margin, rejection=rejection, assigned=choices[cluster]) for row in rows)
    return groups.map(choices), pd.DataFrame(evidence)

def marker_detection(obj,panel):
    columns=["cluster","gene","measured","n_inside","n_outside","detected_inside","detected_outside",
             "rate_inside","rate_outside","difference"]
    if not panel:
        return pd.DataFrame(columns=columns)
    genes=panel_genes(panel)
    measured=pd.Index(genes).isin(obj.var_names)
    indices=obj.var_names.get_indexer(np.asarray(genes)[measured])
    x=sparse.csr_matrix(obj.layers["counts"][:,indices],copy=True)
    x.sum_duplicates()
    x.eliminate_zeros()
    total=x.getnnz(axis=0)
    groups=obj.obs.leiden.astype(str)
    rows=[]
    for cluster in sorted(groups.unique()):
        mask=groups.eq(cluster).to_numpy()
        inside=int(mask.sum());outside=len(mask)-inside
        detected=x[mask].getnnz(axis=0)
        record=pd.DataFrame({"cluster":cluster,"gene":genes,"measured":measured,"n_inside":inside,"n_outside":outside})
        record.loc[measured,"detected_inside"]=detected
        record.loc[measured,"detected_outside"]=total-detected
        record["rate_inside"]=record.detected_inside/inside
        record["rate_outside"]=record.detected_outside/outside if outside else np.nan
        record["difference"]=record.rate_inside-record.rate_outside
        rows.append(record)
    return pd.concat(rows,ignore_index=True)[columns] if rows else pd.DataFrame(columns=columns)

def panel_support(detection, panel, method):
    """Identify type markers missing from the gene axis or silent in every retained cell."""
    columns = ["candidate", "positive_markers", "positive_measured", "positive_detected",
               "required_positive", "axis_sufficient", "detection_sufficient", "missing_ids", "silent_ids"]
    if not panel:
        return pd.DataFrame(columns=columns)
    # Each cluster row partitions the same cells into inside/outside, so their sum is global.
    genes = detection.drop_duplicates("gene").set_index("gene")
    measured = set(genes.index[genes.measured])
    detected = set(genes.index[(genes.detected_inside + genes.detected_outside) > 0])
    required = RULE["min_support"] if method == "specificity" else 1
    rows = []
    for label, markers in panel["types"].items():
        positive = set(markers["positive"])
        on_axis = positive & measured
        expressed = positive & detected
        rows.append([label, len(positive), len(on_axis), len(expressed), required,
                     len(on_axis) >= required, len(expressed) >= required,
                     ",".join(sorted(positive - on_axis)), ",".join(sorted(on_axis - expressed))])
    return pd.DataFrame(rows, columns=columns)

def run_annotation(input_path, output_folder, species, organ, modality, reference, method="specificity"):
    source, out = Path(input_path).resolve(strict=True), Path(output_folder).resolve()
    if out.exists():
        raise ValueError("请选择新的注释结果目录")
    panel = matching_panel(species, organ, modality, reference)
    obj = ad.read_h5ad(source)
    if not obj.n_obs or "counts" not in obj.layers or "leiden" not in obj.obs or not obj.obs_names.is_unique:
        raise ValueError("输入需要整数 counts 层、leiden 分区及唯一条码")
    labels, evidence = annotate_clusters(obj, panel, method)
    detection = marker_detection(obj, panel)
    support = panel_support(detection, panel, method)
    by_cluster = evidence.drop_duplicates("cluster").set_index("cluster")["rejection"] if panel else None
    reason = obj.obs.leiden.astype(str).map(by_cluster).fillna("") if panel else "unsupported_scope"
    details = pd.DataFrame({"cell_type": labels, "cluster":obj.obs.leiden.astype(str),
                            "capture":obj.obs.get("capture","unspecified"),"reason":reason},index=obj.obs_names)
    decisions = details.assign(assigned=details.cell_type.ne("unknown"))
    coverage = decisions.groupby("capture",observed=True).assigned.agg(cells_after_qc="size", assigned="sum")
    coverage["unknown"] = coverage.cells_after_qc - coverage.assigned
    coverage["coverage_after_qc"] = coverage.assigned / coverage.cells_after_qc
    with source.open("rb") as stream:
        input_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = dict(input=str(source), input_sha256=input_hash, method=method, rule=RULE,
                   panel_sha256=hashlib.sha256(json.dumps(panel, sort_keys=True).encode()).hexdigest() if panel else None,
                   species=species, organ=organ, modality=modality, reference=reference, supported=bool(panel),
                   n_cells=len(labels), n_assigned=int(labels.ne("unknown").sum()), output=str(out),
                   panel_type_count=len(support), types_with_required_measured_markers=int(support.axis_sufficient.sum()),
                   types_with_required_detected_markers=int(support.detection_sufficient.sum()))
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        staged = Path(temp)/"annotation"
        staged.mkdir()
        details.to_csv(staged/"annotations.tsv",sep="\t",index_label="cell")
        coverage.to_csv(staged/"coverage.tsv",sep="\t")
        evidence.to_csv(staged/"evidence.tsv",sep="\t",index=False)
        detection.to_csv(staged/"marker_detection.tsv",sep="\t",index=False)
        support.to_csv(staged/"panel_support.tsv",sep="\t",index=False)
        (staged/"receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf8")
        staged.rename(out)
    return receipt

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "out", "species", "organ", "modality", "reference"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--method", choices=("specificity","prevalence"), default="specificity")
    args = parser.parse_args()
    print(json.dumps(run_annotation(args.input,args.out,args.species,args.organ,args.modality,args.reference,args.method),
                     ensure_ascii=False))

if __name__=="__main__":
    main()

