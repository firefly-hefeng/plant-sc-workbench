"""Project-scoped filesystem operations and read-only result views."""
from pathlib import Path
from tempfile import NamedTemporaryFile
import os
import shutil
import subprocess
import sys
from .workspace import child, read_json
from .ports import contract, artifact, task_bindings

FIGURES = {"qc": "逐捕获质控", "pca": "主成分方差", "embedding": "UMAP 聚类与捕获",
           "cluster_comparison": "分辨率与分区稳定性"}


def job_base(store, project, job):
    row=store.job(job)
    if row["project"]!=project:raise ValueError("任务不属于当前项目")
    root=Path(store.project(project)["path"])
    return row,root,child(root,row["output"]).parent


def task_io(store, project, job):
    row,root,base=job_base(store,project,job)
    final=base/"results"/"task-io.json"
    if row["state"]=="succeeded" and final.is_file():
        data=read_json(final)
    else:
        spec=read_json(base/"request.json")
        receipt=base/"results"/"receipt.json"
        historical=row["state"]=="succeeded" and receipt.is_file()
        actual=read_json(receipt) if historical else {}
        data={"schema":"plant-task-io/legacy" if historical else "plant-task-io/pending",
              "action":row["action"],"contract":contract(row["action"],True),
              "inputs":task_bindings(spec,base/"request.json"),
              "outputs":{"products":[artifact(p["path"]) for p in actual.get("outputs",[])]},
              "modules":[],"input_files":actual.get("inputs",[]),"parent_job":spec.get("parent_job")}
        if not historical:
            if (base/"inputs.json").is_file():
                data["input_files"]=read_json(base/"inputs.json")
            data["partial_outputs"]=[artifact(p) for folder in (base/"results",base/"intermediate")
                                     if folder.is_dir() for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix!=".tmp"]
        data["diagnostic"]=row["message"]
    return {**data,"project":project,"job":job,"state":row["state"],"project_path":str(root)}


def plots(store,project,job):
    row,root,base=job_base(store,project,job)
    if row["state"]!="succeeded":raise ValueError("请选择已完成的任务")
    out=base/"results"
    items=[]
    if (out/"cells.tsv").is_file():
        items.append({"id":"umap","title":"交互 UMAP","kind":"interactive","source":(out/"cells.tsv").relative_to(root).as_posix()})
    comparison=out/"cluster_comparison.tsv"
    if comparison.is_file() and not (out/"cluster_comparison.png").is_file():
        items.append({"id":"partition-agreement","title":"分区一致性（ARI）","kind":"partition",
                      "source":comparison.relative_to(root).as_posix()})
    # The scientific report may contain capture-specific FastQC and MultiQC alongside the final figures.
    for p in sorted(out.glob("*.png")):
        items.append({"id":p.stem,"title":FIGURES.get(p.stem,p.stem),"kind":"image","source":p.relative_to(root).as_posix(),
                      "vector":p.with_suffix(".svg").relative_to(root).as_posix() if p.with_suffix(".svg").is_file() else None})
    for folder in (out,base/"intermediate"):
        if folder.is_dir():
            for p in sorted(p for p in folder.rglob("*") if p.suffix.lower() in {".html",".htm"} and p.is_file() and "code" not in p.relative_to(folder).parts):
                title={"report.html":"分析报告","multiqc_report.html":"MultiQC · 文库质检汇总"}.get(p.name,p.name)
                items.append({"id":p.relative_to(base).as_posix(),"title":title,"kind":"report","source":p.relative_to(root).as_posix()})
    return {"items":items,"job":job,"action":row["action"],"project":project}


def safe_name(name):
    name=str(name).strip()
    if (not name or name in (".","..") or any(c in name for c in '/\\:*?"<>|') or
        name.endswith(("."," ")) or Path(name).is_reserved() or any(ord(c)<32 for c in name)):
        raise ValueError("请输入有效的单个文件或文件夹名称")
    return name


def writable_project_dir(store,q):
    root=Path(store.project(q["project"])["path"]).resolve()
    if q.get("scope")=="input":raise ValueError("输入目录为只读")
    folder=child(root,q.get("directory",""))
    if not folder.is_dir():raise ValueError("目标目录不存在")
    if folder.is_relative_to(root/"runs"):raise ValueError("运行归档保持只读，请选择项目的其他目录")
    return root,folder


def make_dir(store,q):
    root,folder=writable_project_dir(store,q)
    target=child(root,folder/safe_name(q["name"]))
    if target.is_relative_to(root/"runs"):raise ValueError("runs 为运行归档目录")
    target.mkdir(exist_ok=False)
    return {"path":target.relative_to(root).as_posix()}


def copy_file(store,q):
    source=store.locate(q)[1]
    if not source.is_file():raise ValueError("请选择要复制的文件")
    root,folder=writable_project_dir(store,{"project":q["project"],"directory":q.get("directory","")})
    target=child(root,folder/safe_name(q.get("name") or source.name))
    if target.is_relative_to(root/"runs"):raise ValueError("运行归档保持只读")
    # Publish only a complete copy. Never overwrite an existing destination.
    with NamedTemporaryFile(dir=folder,prefix=".copy-",delete=False) as out:
        tmp=Path(out.name)
        try:
            with source.open("rb") as src:shutil.copyfileobj(src,out,1024*1024)
        except BaseException:
            out.close();tmp.unlink(missing_ok=True);raise
    try:
        if os.name=="nt":os.rename(tmp,target)
        else:os.link(tmp,target)
    finally:
        tmp.unlink(missing_ok=True)
    return {"path":target.relative_to(root).as_posix()}


def reveal(store,q):
    path=store.locate(q)[1]
    if not path.exists():raise ValueError("项目路径已不存在")
    if os.name=="nt":
        if path.is_dir():os.startfile(str(path))
        else:subprocess.Popen(["explorer.exe","/select,",str(path)])
    elif sys.platform=="darwin":
        subprocess.Popen(["open","-R",str(path)])
    else:
        subprocess.Popen(["xdg-open",str(path if path.is_dir() else path.parent)])
    return {"path":str(path)}

