"""Import discovery and parameter defaults for a local experiment."""
from pathlib import Path
import csv
import re

DEFAULTS = dict(min_counts=1, min_genes=1, mad_multiplier=4.0, max_mito_pct=None,
                max_plastid_pct=None, doublet_mode="report", expected_doublet_rate=0.05,
                hvg=2000, n_pcs=30, n_neighbors=15, resolutions=[0.5, 1.0],
                seed=42, integration="none", feature_join="strict", cell_calling="upstream",
                ambient_mode="off", threads=4, memory_gb=16, include_introns=True, chemistry="auto",
                analysis_layer="counts",hvg_method="seurat",target_sum=10000,min_dist=0.5,lower=100,fdr=0.01,
                quantifier="starsolo",run_read_qc=True,graph_representation="auto")
FASTQ = re.compile(r"(.+?)_S\d+_(?:L\d{3}_)?R[12]_\d+\.fastq\.gz$", re.I)
def absolute(value):
    if not value or not str(value).strip():
        raise ValueError("请先选择本地文件或目录。")
    return Path(str(value).strip().strip('"')).expanduser().resolve(strict=True)

def is_mex(p):
    return p.is_dir() and any((p / name).is_file() for name in ("matrix.mtx", "matrix.mtx.gz"))

def raw_matrix(path):
    name=path.name.lower()
    return name=="raw" or "raw_feature" in name or "unfiltered" in name

def matrix_family(path):
    if path.name.lower() in ("raw","filtered"):return "starsolo"
    if "feature_bc_matrix" in path.name.lower():return "tenx"
    return ""

def discover(value):
    root = absolute(value)
    if root.is_file() and root.suffix.lower() in (".csv", ".tsv"):
        with root.open(encoding="utf-8-sig", newline="") as f:
            records=list(csv.DictReader(f,delimiter="\t" if root.suffix.lower()==".tsv" else ","))
        if not records or not {"path","id"} <= records[0].keys():
            raise ValueError("样本表需含 id、path 两列，其余元数据可选。")
        for row in records:
            for key in ("path","filtered_path","raw_path","clusters_tsv","corrected_path"):
                if row.get(key):
                    row[key]=str(absolute(root.parent/row[key]))
            row.setdefault("kind","fastq" if row.get("prefix") else ("raw" if raw_matrix(Path(row["path"])) else "matrix"))
            if not row.get("sample"):row["sample"]=row["id"]
        return records
    if root.is_file() and (root.name in ("matrix.mtx","matrix.mtx.gz") or FASTQ.match(root.name)):
        root=root.parent
    def rec(p,depth):
        if is_mex(p) or (p.is_file() and p.suffix.lower() in (".h5ad",".h5")):
            return [(p, "raw" if raw_matrix(p) else "matrix", "")]
        if depth==0 or not p.is_dir():
            return []
        kids=sorted((x for x in p.iterdir() if not x.name.startswith(".") and not x.is_symlink()),key=lambda x:x.name.lower())
        fq=sorted({m[1] for x in kids if (m:=FASTQ.match(x.name))})
        if fq:
            return [(p,"fastq",pre) for pre in fq]
        out=[]
        for x in kids:
            if x.name in ("runs","__pycache__","node_modules") or (x.is_dir() and x.name in ("analysis","cloupe","spatial")): continue
            if len(out)>256: raise ValueError("检测到过多输入，请选择具体项目的输入目录。")
            out.extend(rec(x,depth-1))
        return out
    candidates=rec(root,4)
    # Prefer one representation per 10x outs directory: MEX and H5 hold the same counts.
    bykey={}
    for p,kind,pre in candidates:
        key=(p.parent,kind,p.stem,pre)
        if key not in bykey or p.is_dir():bykey[key]=(p,kind,pre)
    candidates=list(bykey.values()); rows=[];used=set()
    for p,kind,pre in candidates:
        if (p,kind,pre) in used:continue
        pair=None
        if kind in ("matrix","raw") and matrix_family(p):
            pair=next((q for q in candidates if q[0].parent==p.parent and q[1]!=kind and matrix_family(q[0])==matrix_family(p)),None)
        name=pre or p.stem
        if "feature_bc_matrix" in name or name=="outs":name=p.parent.parent.name if p.parent.name=="outs" else p.parent.name
        if matrix_family(p)=="starsolo":name=p.parent.parent.parent.name if p.parent.parent.name=="Solo.out" else p.parent.name
        row=dict(id=name,sample=name,path=str(p),kind=kind,counts_layer="")
        if pre:row["prefix"]=pre
        if pair:
            used.add(pair);raw=p if kind=="raw" else pair[0];filtered=pair[0] if kind=="raw" else p
            row.update(path=str(raw),kind="raw",filtered_path=str(filtered))
        rows.append(row)
    seen=set()
    for no,row in enumerate(rows,1):
        name=row["id"];base=name
        while name in seen:name=f"{base}-{no}";no+=1
        seen.add(name);row["id"]=name
    if not rows:raise ValueError("未找到 10x MEX、GEX H5、H5AD、标准命名 FASTQ 或样本表。")
    return rows

