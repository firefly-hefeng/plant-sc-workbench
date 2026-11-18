"""RNA UMI quantification with a local Linux/WSL STARsolo worker."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from .workspace import ROOT,write_json
from .blocks import block
from . import upstream

ASSETS=ROOT/".runtime"/"starsolo"
def linux_path(p):
    path=Path(p).resolve()
    if os.name!="nt":return str(path)
    if len(path.drive)!=2:raise ValueError("WSL 计算端需要可挂载的本地盘符路径。")
    return "/mnt/"+path.drive[0].lower()+"/"+"/".join(path.parts[1:])
def runtime():
    bundled=ASSETS/"STAR";found=str(bundled) if bundled.is_file() else shutil.which("STAR")
    if not found or (os.name=="nt" and not shutil.which("wsl")):return False
    return True
def call(job,out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    job.update(output=linux_path(out),binary=linux_path(ASSETS/"STAR") if (ASSETS/"STAR").is_file() else "STAR")
    config=out/"star-run.json";write_json(config,job)
    driver=ROOT/"backend"/"star_driver.py"
    args=["wsl.exe","-e","python3",linux_path(driver),linux_path(config)] if os.name=="nt" else [sys.executable,str(driver),str(config)]
    with (out/"star.log").open("wb") as log:p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:raise ValueError("STARsolo 执行失败，见 "+str(out/"star.log"))
def index_assets(fasta,gtf,out,threads=4,memory_gb=16):
    out=Path(out).resolve()
    if (out/"Genome").exists():raise ValueError("请选择新的索引目录。")
    call(dict(mode="index",fasta=linux_path(fasta),gtf=linux_path(gtf),threads=threads,memory_gb=memory_gb),out)
    if not (out/"Genome").is_file() or not (out/"SAindex").is_file():raise ValueError("STAR 索引不完整。")
    desc={"reference_dir":str(out),"fasta_sha256":upstream._file_sha(fasta),"gtf_sha256":upstream._file_sha(gtf),"engine":"STAR 2.7.11b"}
    write_json(out/"index-source.json",desc);return desc
def quantification_assets(params):
    index = Path(params.get("star_index") or ASSETS/"TAIR10-62-index").resolve()
    whitelist = Path(params.get("whitelist") or ASSETS/"3M-february-2018.txt").resolve()
    return index, whitelist


@block("quantify")
def quantify(lib,params,out):
    if not runtime():raise ValueError("需要 Linux 或 WSL 和 STAR 2.7.11b。")
    idx, wl = quantification_assets(params)
    if not all((idx/p).is_file() for p in ("Genome","SA","SAindex","genomeParameters.txt")) or not wl.is_file():
        raise ValueError("请选择完整的 STAR 索引和与 10x 3′ v3/v3.1 匹配的条码白名单。")
    plan=upstream.plan_fastq(lib["path"],lib["prefix"],None,threads=params["threads"],chemistry=params["chemistry"])
    reads=iter(plan["files"]);pairs=[[linux_path(r1),linux_path(r2)] for r1,r2 in zip(reads,reads)]
    feature="GeneFull" if params["include_introns"] else "Gene";out=Path(out)
    umi_length=10 if params["chemistry"]=="SC3Pv3_10" else 12
    call(dict(mode="count",pairs=pairs,umi_length=umi_length,feature=feature,index=linux_path(idx),whitelist=linux_path(wl),threads=params["threads"]),out)
    raw=out/"Solo.out"/feature/"raw";filtered=raw.parent/"filtered"
    if not (raw/"matrix.mtx").is_file():raise ValueError("STARsolo 没有产生原始计数矩阵。")
    meta={"raw_path":str(raw),"filtered_path":str(filtered) if (filtered/"matrix.mtx").is_file() else None,
          "feature":feature,"umi_length":umi_length,"chemistry":params["chemistry"],"engine":"STARsolo 2.7.11b","index":str(idx),"whitelist_sha256":upstream._file_sha(wl),
          "input_fastqs":plan["files"],"whitelist":str(wl)}
    manifest=idx/"index-source.json"
    if manifest.is_file():meta["reference_identity"]=__import__("json").loads(manifest.read_text(encoding="utf-8"))
    write_json(out/"quantification.json",meta);return meta

