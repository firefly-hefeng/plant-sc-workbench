"""Metadata-only reference recommendations; no expression data leave the host."""
from pathlib import Path
import gzip
import h5py
from .resources import list_references, resolve_reference

def feature_ids(path):
    p=Path(path)
    if p.is_dir():
        options=("features.tsv.gz","features.tsv","genes.tsv.gz","genes.tsv")
        f=next((p/n for n in options if (p/n).is_file()),None)
        if not f:return set()
        with (gzip.open if f.suffix==".gz" else open)(f,"rt",encoding="utf-8") as stream:
            return {parts[0] for line in stream if (parts:=line.rstrip("\r\n").split("\t")) and (len(parts)<3 or parts[2]=="Gene Expression")}
    if p.suffix.lower() not in (".h5",".h5ad"):return set()
    with h5py.File(p) as f:
        if "matrix/features/id" in f:
            group=f["matrix/features"]
            ids=group["id"].asstr()[:]
            return set(ids[group["feature_type"].asstr()[:]=="Gene Expression"]) if "feature_type" in group else set(ids)
        elif "var" in f:
            index=f["var"].attrs.get("_index","_index")
            d=f["var"].get("gene_ids",f["var"][index])
            if isinstance(d,h5py.Group) and "categories" in d:
                categories=d["categories"].asstr()[:]
                return {categories[v] for v in set(d["codes"][:]) if v>=0}
        else:return set()
        return set(d.asstr()[:]) if isinstance(d,h5py.Dataset) else set()
def recommendation(libs):
    candidates=[resolve_reference(r["id"]) for r in list_references()]
    per_capture=[]
    for lib in libs:
        if lib.get("kind")=="fastq":return None
        ids=feature_ids(lib["path"])
        scores=[]
        for r in candidates:
            mt=len(ids.intersection(r["mitochondrial"]));pt=len(ids.intersection(r["plastid"]))
            if mt+pt:scores.append({"id":r["id"],"mitochondrial":mt,"plastid":pt,"matches":mt+pt})
        scores.sort(key=lambda x:-x["matches"])
        # Sparse overlap can arise from assembly-independent symbols. Only one unambiguous candidate is suggested.
        if not scores or scores[0]["matches"]<5 or (len(scores)>1 and scores[1]["matches"]*2>=scores[0]["matches"]):return None
        per_capture.append({"capture":lib["id"],**scores[0]})
    if not per_capture or len({r["id"] for r in per_capture})!=1:return None
    return {"id":per_capture[0]["id"],"reason":"各捕获基因轴与该集合的稳定 ID 匹配；请核对实际建库参考版本。","captures":per_capture}

