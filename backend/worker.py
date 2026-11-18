"""A reproducible, isolated analysis process. The parent owns cancellation."""
from pathlib import Path
from hashlib import sha256
import inspect
import json
import os
import platform
import shutil
import sys
import traceback
from importlib.metadata import version, PackageNotFoundError
from .workspace import ROOT, read_json, write_json, timestamp
from . import upstream
from .ports import concrete_manifest, SINGLE_MODULES
from .blocks import event, recipe, trace_to, step

def file_id(path):
    p=Path(path);h=sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(2**20),b""):h.update(block)
    return {"path":str(p),"bytes":p.stat().st_size,"sha256":h.hexdigest()}

def matrix_files(path):
    p = Path(path)
    if p.is_file():
        return [p]
    from .qc import source_files
    return source_files(p)


def input_identities(spec):
    """Freeze consumed external files once, including parent sidecars and index assets."""
    cfg = spec["params"]
    paths = set()
    has_reads = False
    for lib in spec["libraries"]:
        if lib.get("kind") == "fastq":
            has_reads = True
            selected = upstream.plan_fastq(lib["path"], lib["prefix"], None, chemistry=cfg["chemistry"])
            paths.update(Path(p) for p in selected["files"])
        else:
            paths.update(matrix_files(lib["path"]))
        for field in ("raw_path", "filtered_path", "corrected_path", "clusters_tsv"):
            if lib.get(field):
                paths.update(matrix_files(lib[field]))
    if has_reads and spec["action"] in ("analysis", "quality", "quantify"):
        if cfg["quantifier"] == "starsolo":
            from .starsolo import quantification_assets
            index, whitelist = quantification_assets(cfg)
            paths.add(whitelist)
        else:
            index = Path(cfg["reference_dir"])
        for f in index.rglob("*"):
            if f.is_file() and (f.name in ("Genome", "SA", "SAindex", "reference.json", "index-source.json", "genomeParameters.txt")
                                or f.name.startswith("chr") or f.suffix in (".tab", ".gtf", ".fa", ".fai", ".gz", ".bed", ".txt")):
                paths.add(f)
    parent = spec.get("checkpoint_h5ad") or spec.get("graph_h5ad")
    if parent:
        source = Path(parent)
        paths.add(source)
        sidecars = ["summary.json", "qc_cells.tsv", "qc_libraries.tsv"]
        if spec.get("checkpoint_h5ad"):
            sidecars.append("receipt.json")
        else:
            sidecars.extend(["environment.json", "pca_variance.tsv", "qc.png", "qc.svg"])
        paths.update(source.parent / name for name in sidecars if (source.parent / name).is_file())
    if spec.get("source_h5ad"):
        paths.add(Path(spec["source_h5ad"]))
    if spec.get("custom_reference"):
        paths.add(Path(spec["custom_reference"]))
    paths.update(Path(cfg[k]) for k in ("fasta", "gtf", "clusters_tsv") if cfg.get(k))
    return [file_id(p) for p in sorted({p.resolve() for p in paths})]

def run(base):
    base=Path(base).resolve(); spec=read_json(base/"request.json");action=spec["action"];params=spec["params"]
    out=base/"results";out.mkdir(exist_ok=False)
    trace_to(base/"block-events.jsonl")
    tools=upstream.capabilities()
    workflow=recipe(spec,tools)
    write_json(base/"workflow.json",workflow)
    if not workflow["ready"]:
        raise ValueError("；".join(reason for row in workflow["blocks"] for reason in row["issues"]))
    implementation=sorted((ROOT/"backend").glob("*.py"))+sorted((ROOT/"resources"/"r").glob("*.R"))
    initial_sources=[file_id(p) for p in implementation]
    def progress(value,message=""):
        if isinstance(value,str) and not isinstance(message,str):value,message=message,value
        if isinstance(value,str):value,message=5,value
        write_json(base/"progress.json",dict(progress=max(0,min(99,int(value))),message=str(message)))
    progress(1,"核对输入与参考");started=timestamp()
    receipts=[]
    ids=input_identities(spec)
    write_json(base/"inputs.json",ids)
    if action in SINGLE_MODULES:
        from .component_jobs import run_component
        source=next(r for r in ids if r["path"]==spec["source_h5ad"])
        if source["sha256"]!=spec["source_sha256"]:
            raise ValueError("来源计算对象的指纹与提交时的登记值不符")
        run_component(spec,out)
    elif action=="recluster":
        from .analysis import recluster
        recluster(spec["graph_h5ad"],out,params["resolutions"],seed=params["seed"],progress=progress)
    elif action=="build_reference":
        with step("reference"):
            if params["quantifier"]=="starsolo":
                from .starsolo import index_assets
                receipts.append(index_assets(params["fasta"],params["gtf"],out/"reference",int(params["threads"]),int(params["memory_gb"])))
            else:
                receipts.append(upstream.build_reference(params["fasta"],params["gtf"],out/"reference",name=params.get("ref_name","plant_ref"),threads=int(params["threads"]),memory_gb=int(params["memory_gb"])))
        receipts[-1]["component"]="reference"
    else:
        for idx,lib in enumerate(spec["libraries"]):
            stage=base/"intermediate"/f"capture-{idx+1:03d}";kind=lib.get("kind","matrix")
            if action in ("read_qc","quantify") and kind!="fastq":raise ValueError("测序质检和定量动作需要 FASTQ 文库。")
            if kind=="fastq":
                if not lib.get("prefix"):raise ValueError("请核对该捕获的 FASTQ 样本名前缀。")
                dest=out if action in ("read_qc","quantify") else stage
                loc=dest/f"capture-{idx+1:03d}"
                if action=="read_qc":
                    # read_qc only needs FASTQs. Preserve actual prefix and read identities.
                    plan=upstream.plan_fastq(lib["path"],lib["prefix"],params.get("reference_dir") or None,
                          include_introns=params["include_introns"],chemistry=params["chemistry"],threads=params["threads"],memory_gb=params["memory_gb"])
                    receipts.append(dict(upstream.read_qc(plan,loc,progress=progress),component="reads",capture=lib["id"]));continue
                if params["quantifier"]=="starsolo":
                    from .starsolo import quantify
                    if params.get("run_read_qc"):
                        plan=upstream.plan_fastq(lib["path"],lib["prefix"],None,threads=params["threads"],chemistry=params["chemistry"])
                        receipts.append(dict(upstream.read_qc(plan,loc/"read_qc",progress=progress),component="reads",capture=lib["id"]))
                    data=quantify(lib,params,loc/"quantification")
                else:
                    plan=upstream.plan_fastq(lib["path"],lib["prefix"],params["reference_dir"],include_introns=params["include_introns"],
                              chemistry=params["chemistry"],threads=params["threads"],memory_gb=params["memory_gb"])
                    if params.get("run_read_qc"):
                        receipts.append(dict(upstream.read_qc(plan,loc/"read_qc",progress=progress),component="reads",capture=lib["id"]))
                    data=upstream.run_fastq(plan,loc/"count",progress=progress,run_read_qc=False)
                receipts.append(dict(data,component="quantify",capture=lib["id"]))
                if action=="quantify":continue
                lib.update(path=data["raw_path"],filtered_path=data["filtered_path"],kind="raw");kind="raw"
            if kind not in ("raw","fastq") and params["cell_calling"]=="emptydrops" and lib.get("raw_path"):
                lib.update(filtered_path=lib["path"],path=lib["raw_path"],kind="raw");kind="raw"
            if kind=="raw":
                raw=lib["path"];filtered=lib.get("filtered_path")
                if not filtered or params["cell_calling"]=="emptydrops":
                    if not any(b["id"]=="call" for b in workflow["blocks"]):
                        workflow=recipe(read_json(base/"request.json"),tools,requires_call=True)
                        write_json(base/"workflow.json",workflow)
                        if not workflow["ready"]:
                            raise ValueError("上游未产生候选细胞矩阵，需要安装 DropletUtils 或提供过滤矩阵")
                    data=upstream.call_droplets(raw,stage/"called",fdr=float(params.get("fdr",0.01)),lower=int(params.get("lower",100)),seed=int(params["seed"]))
                    filtered=data["filtered_path"];receipts.append(dict(data,component="call",capture=lib["id"]))
                lib.update(raw_path=raw,path=str(filtered),kind="matrix")
            if action in ("analysis","quality") and params["ambient_mode"]=="soupx":
                if not lib.get("raw_path"):raise ValueError("SoupX 需要同一次捕获的未过滤液滴矩阵。")
                clusters=lib.get("clusters_tsv") or params.get("clusters_tsv")
                if not clusters:
                    from .ambient import provisional_groups
                    clusters=provisional_groups(lib["path"],stage,int(params["seed"]))
                data=upstream.correct_ambient(lib["raw_path"],lib["path"],clusters,stage/"soupx")
                lib["corrected_path"]=str(data["corrected_path"]);receipts.append(dict(data,component="ambient",capture=lib["id"],clusters_tsv=str(clusters)))
        if action in ("analysis","quality","from_qc"):
            from .analysis import run_analysis
            run_analysis(spec,out,progress=progress)
    event("export","started")
    env={"python":sys.version,"platform":platform.platform(),"threads":{k:os.getenv(k) for k in ("OMP_NUM_THREADS","NUMBA_NUM_THREADS","OPENBLAS_NUM_THREADS")}}
    for pkg in ("scanpy","numpy","h5py","pandas","scipy","anndata","matplotlib","igraph","leidenalg","harmonypy","umap-learn","scikit-learn","pynndescent","scikit-misc"):
        try:env[pkg]=version(pkg)
        except PackageNotFoundError:pass
    write_json(out/"execution-environment.json",env)
    shutil.copyfile(base/"request.json",out/"parameters.json")
    shutil.copyfile(base/"inputs.json",out/"inputs.json")
    shutil.copyfile(base/"workflow.json",out/"workflow.json")
    shutil.copyfile(ROOT/"backend"/"replay_run.py",out/"replay.py")
    backend_hashes=[file_id(p) for p in implementation]
    if initial_sources!=backend_hashes:raise RuntimeError("计算期间组件版本发生变化，请使用冻结版本重试。")
    write_json(out/"source-versions.json",backend_hashes)
    # Archive the exact analysis implementation for review, independent of later updates.
    code=out/"code";code.mkdir(exist_ok=True)
    for p in implementation:shutil.copy2(p,code/p.name)
    event("export","completed")
    shutil.copyfile(base/"block-events.jsonl",out/"block-events.jsonl")
    outputs=[file_id(p) for p in sorted(out.rglob("*")) if p.is_file() and p!=out/"receipt.json"]
    # Include durable upstream products in the inventory even in an end-to-end task.
    intermediates=base/"intermediate"
    if intermediates.is_dir():
        outputs.extend(file_id(p) for p in sorted(intermediates.rglob("*")) if p.is_file())
    plan=read_json(base/"workflow.json")
    manifest=concrete_manifest(base,spec,plan,receipts,ids,outputs)
    write_json(out/"task-io.json",manifest)
    outputs.append(file_id(out/"task-io.json"))
    def jsonable(item):
        if isinstance(item,Path):return str(item)
        if isinstance(item,dict):return {k:jsonable(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)):return [jsonable(v) for v in item]
        return item
    write_json(out/"receipt.json",dict(status="completed",action=action,started=started,finished=timestamp(),inputs=ids,outputs=outputs,
        reference=spec["reference"].get("id"),parent_job=spec.get("parent_job"),upstream=jsonable(receipts)))
    progress(99,"结果已写入并计算校验值")
if __name__=="__main__":
    directory=Path(sys.argv[1])
    try:run(directory)
    except Exception as e:
        write_json(directory/"error.json",{"type":type(e).__name__,"message":str(e),"time":timestamp()})
        traceback.print_exc();sys.exit(1)

