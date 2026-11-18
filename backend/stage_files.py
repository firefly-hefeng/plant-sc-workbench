"""Small project-scoped result index for the active work position, including legacy jobs."""
from pathlib import Path
from .project_views import job_base
from .workspace import read_json

MODULES={1:{"reads","reference","quantify"},2:{"qc","merge","ambient","call"},
         3:{"features","pca"},4:{"graph","leiden","umap"},5:{"export"}}
PREFERRED={1:("multiqc_report.html","web_summary.html","quantification.json"),
           2:("qc.png","qc_cells.tsv","qc_libraries.tsv","qc.h5ad"),
           3:("pca.png","pca_variance.tsv","component.h5ad","analysis.h5ad"),
           4:("embedding.png","cluster_comparison.png","cluster_comparison.tsv","cluster_samples.tsv","cells.tsv","component.h5ad","analysis.h5ad"),
           5:("analysis.h5ad","component.h5ad","qc.h5ad","report.html","task-io.json","parameters.json","receipt.json")}


def list_files(store,project,job,step):
    if step not in MODULES:raise ValueError("未知工作位")
    row,root,base=job_base(store,project,job)
    out=base/"results"
    if row["state"]!="succeeded":return {"items":[],"directory":row["output"]}
    items={}
    def include(path,selector=None):
        p=Path(path).resolve()
        if not p.is_relative_to(base) or not p.exists():return
        key=p.relative_to(root).as_posix()
        entry=items.setdefault(key,{"path":key,"name":p.name,"type":"dir" if p.is_dir() else "file","selectors":[]})
        if selector and selector not in entry["selectors"]:entry["selectors"].append(selector)
    for name in PREFERRED[step]:
        include(out/name)
    manifest=out/"task-io.json"
    if manifest.is_file() and step!=5:
        for m in read_json(manifest)["modules"]:
            if m["module"] in MODULES[step]:
                for values in m["outputs"].values():
                    for value in values:
                        if value.get("path"):include(value["path"],value.get("selector"))
    elif step==1:
        for parent in (out,base/"intermediate"):
            if parent.is_dir():
                for path in parent.rglob("*.html"):
                    if path.name.endswith(("_fastqc.html","multiqc_report.html","web_summary.html")):include(path)
    return {"items":list(items.values()),"directory":row["output"],"job":job,"project":project}

