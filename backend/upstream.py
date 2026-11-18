"""10x 3' UMI upstream adapters. Paths refer to local data; no uploads."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from .blocks import block

PROJECT = Path(__file__).resolve().parents[1]
R_SCRIPTS = PROJECT / "resources" / "r"
SAMPLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}")
FASTQ_NAME = re.compile(r"(.+)_S(\d+)_(?:L(\d{3})_)?R([12])_(\d{3})\.fastq\.gz")


def _file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rscript():
    private=PROJECT / ".runtime" / "R-4.6.2" / "app" / "bin" / "x64" / "Rscript.exe"
    if os.name=="nt" and private.is_file():return str(private)
    found = shutil.which("Rscript")
    if found or os.name != "nt":
        return found
    programs = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "R"
    candidates = sorted(programs.glob("R-*/bin/Rscript.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


def _r_env():
    env = os.environ.copy()
    private = PROJECT / ".runtime" / "Rlibrary"
    if private.is_dir():
        # R_LIBS preserves existing R_LIBS_USER library discovery.
        env["R_LIBS"] = os.pathsep.join(filter(None, [str(private), env.get("R_LIBS")]))
    if os.name == "nt":
        env["LC_ALL"] = "English_United States.utf8"
        # Batch workers do not need cli's native progress ticker.
        env["CLI_NO_THREAD"]="1"
    return env


def _java_path(runtime):
    java = runtime/"jre"/"bin"/"java.exe"
    if os.name!="nt" or str(java).isascii() or not java.is_file():
        return java
    # Older Windows JVM launchers cannot load native libraries from Unicode installation paths.
    # A verified directory junction keeps the runtime in the independent project.
    target=runtime/"jre"
    token=hashlib.sha256(str(target).encode()).hexdigest()[:12]
    alias=Path(os.environ["LOCALAPPDATA"])/"PlantSC-Workbench"/"runtime"/("jre-"+token)
    if not alias.exists():
        alias.parent.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ, PLANT_JRE_ALIAS=str(alias),PLANT_JRE_TARGET=str(target))
        subprocess.run(["powershell.exe","-NoProfile","-Command",
                        "New-Item -ItemType Junction -Path $env:PLANT_JRE_ALIAS -Target $env:PLANT_JRE_TARGET -ErrorAction Stop | Out-Null"],
                       env=env,capture_output=True,check=False)
    if not alias.is_dir() or not alias.samefile(target):
        return java
    return alias/"bin"/"java.exe"


def read_tools():
    fast=shutil.which("fastqc")
    multi=shutil.which("multiqc")
    runtime=PROJECT / ".runtime"
    if not multi and (runtime/"reads-env/Scripts/multiqc.exe").is_file():
        multi=str(runtime/"reads-env/Scripts/multiqc.exe")
    if fast:return [fast],multi
    java=_java_path(runtime)
    qc=runtime/"FastQC"
    if not java.is_file() or not (qc/"uk/ac/babraham/FastQC/FastQCApplication.class").is_file():
        return [],multi
    cp=os.pathsep.join([str(qc),str(qc/"*")])
    return [str(java),"-Djava.awt.headless=true","-Dfastqc.nogroup=true","-Xmx1g","-cp",cp,
            "uk.ac.babraham.FastQC.FastQCApplication"],multi


def capabilities():
    from .starsolo import ASSETS,runtime
    current=dict(_detected_tools())
    linux=PROJECT/".runtime"/"soupx-linux"/"runtime.json"
    if os.name=="nt" and linux.is_file():
        info=json.loads(linux.read_text(encoding="utf-8"))
        current["soupx"]={"available":True,"version":info["version"],"detail":"WSL / conda-forge"}
    current["starsolo"]={"available":runtime(),"version":"2.7.11b","detail":"Linux / WSL",
                          "tair10_index":(ASSETS/"TAIR10-62-index"/"index-source.json").is_file()}
    return current


@lru_cache(maxsize=1)
def _detected_tools():
    rs = _rscript()
    result = {}
    for name in ("cellranger", "fastqc", "multiqc", "Rscript"):
        cmd = rs if name == "Rscript" else shutil.which(name)
        available = bool(cmd) and (name != "cellranger" or platform.system() == "Linux")
        result[name] = {"available": available, "path": cmd or "", "detail":
                        "可用" if available else ("需 Linux 执行端安装 Cell Ranger 10" if name == "cellranger" else "未检测到程序")}
    packages = {"emptydrops": "DropletUtils", "soupx": "SoupX"}
    fq,mq=read_tools()
    for name,cmd in (("fastqc",fq[0] if fq else None),("multiqc",mq)):
        result[name]={"available":bool(cmd),"path":cmd or "","detail":"可用" if cmd else "未检测到程序"}
    versions = {}
    if rs:
        expr = ('for (p in c("DropletUtils","SoupX")) {if(nzchar(system.file(package=p))) '
                'cat(p, as.character(packageVersion(p)), "\\n")}')
        try:
            proc = subprocess.run([rs, "--vanilla", "-e", expr], env=_r_env(),
                                  capture_output=True, text=True, timeout=10, check=False)
            for row in proc.stdout.splitlines():
                pair = row.split()
                if len(pair) == 2:
                    versions[pair[0]] = pair[1]
        except (OSError, subprocess.TimeoutExpired):
            pass
    for name, package in packages.items():
        result[name] = {"available": package in versions, "version": versions.get(package, ""),
                        "detail": versions.get(package, f"需 R 包 {package}")}
    return result


def _bounded_int(n, label, low, high):
    if type(n) is not int or not low <= n <= high:
        raise ValueError(f"{label}应为 {low}–{high} 的整数。")
    return n


def _report(progress, text):
    if progress:
        progress(text)


def _dir(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"上游任务需要一个空输出目录：{path}")
    return path


def _run(args, folder, tag, env=None):
    log = folder / f"{tag}.log"
    with log.open("wb") as stream:
        returncode = subprocess.run(args,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,
                                    env=env,check=False).returncode
    if returncode:
        tail = log.read_bytes()[-1200:].decode("utf-8",errors="replace")
        raise RuntimeError(f"{tag} 退出码 {returncode}。日志 {log}\n{tail}")
    return log


def _receipt(folder, info):
    path = folder / "receipt.json"
    _json(path, {**info, "completed_at": datetime.now(timezone.utc).isoformat()})
    return {**info, "receipt": str(path)}


def _cellranger():
    binary = shutil.which("cellranger")
    if platform.system() != "Linux" or not binary:
        raise RuntimeError("此计算端缺少 Linux Cell Ranger 10。请在装有 Cell Ranger 10 的 Linux 端运行，或导入已有计数矩阵。")
    version = subprocess.check_output([binary, "--version"], text=True, timeout=20).strip()
    if not re.search(r"\b10\.\d+\.\d+\b", version):
        raise ValueError(f"本适配器支持 Cell Ranger 10；检测到 {version}")
    return binary, version


def _first_record(path):
    with gzip.open(path, "rb") as stream:
        h, seq, plus, quality = (stream.readline().strip() for _ in range(4))
    if not h.startswith(b"@") or not plus.startswith(b"+") or len(seq) != len(quality) or not seq:
        raise ValueError(f"FASTQ 首条记录不合法：{path.name}")
    return re.sub(br"/[12]$", b"", h.split()[0]), len(seq)


def plan_fastq(fastq_dir, sample, reference_dir, *, include_introns=True,
               chemistry="auto", threads=4, memory_gb=16):
    if not SAMPLE.fullmatch(sample or ""):
        raise ValueError("请输入 FASTQ 文件名中的完整样本前缀。")
    if type(include_introns) is not bool or chemistry not in ("auto", "SC3Pv3", "SC3Pv3_10"):
        raise ValueError("支持 10x 3′ v3/v3.1，请显式指定是否计入内含子。")
    _bounded_int(threads, "线程数", 1, 512)
    _bounded_int(memory_gb, "内存 GB", 1, 4096)
    root = Path(fastq_dir).resolve(strict=True)
    reference = Path(reference_dir).resolve(strict=True) if reference_dir else None
    mandatory = ["reference.json", "fasta/genome.fa", "star/Genome", "star/genomeParameters.txt"]
    if reference is not None and (not all((reference / f).is_file() for f in mandatory) or not any(
            (reference / "genes" / f).is_file() for f in ("genes.gtf", "genes.gtf.gz"))):
        raise ValueError("此目录缺少 Cell Ranger 已构建参考的索引、FASTA、GTF 或 reference.json。")
    pairs = {}
    for file in sorted(root.glob("*.fastq.gz")):
        m = FASTQ_NAME.fullmatch(file.name)
        if m and m[1] == sample:
            pairs.setdefault((m[2], m[3], m[5]), {})[m[4]] = file
    if not pairs or any(set(p) != {"1", "2"} for p in pairs.values()):
        raise ValueError("输入目录下找不到完整 R1/R2 配对；请检查样本前缀和 lane。")
    files = []
    for p in pairs.values():
        h1, length1 = _first_record(p["1"])
        h2, _ = _first_record(p["2"])
        if h1 != h2:
            raise ValueError(f"首条读段的配对名称不匹配：{p['1'].name}")
        minimum = 26 if chemistry=="SC3Pv3_10" else 28
        if length1 < minimum:
            raise ValueError(f"所选 10x v3 布局需要 R1 至少 {minimum} nt，实测 {length1} nt。请核对建库记录；已确认 v3 且仅测 10 nt UMI 时可显式选择短 UMI 布局。")
        files.extend([str(p["1"]), str(p["2"])])
    return dict(fastq_dir=str(root), sample=sample, reference_dir=str(reference) if reference else None,
                include_introns=include_introns, chemistry=chemistry, threads=threads,
                memory_gb=memory_gb, files=files, pairs=len(pairs))


@block("reads")
def read_qc(plan, outdir, progress=None):
    plan = plan_fastq(**{k:v for k,v in plan.items() if k not in ("files","pairs")})
    fastqc, multiqc = read_tools()
    if not fastqc or not multiqc:
        raise RuntimeError("需在运行工作台的计算端安装 FastQC 和 MultiQC 后才能汇总测序质量。")
    folder = _dir(outdir)
    _report(progress, "正在计算逐文件 FastQC")
    if len(fastqc)>1:
        args = fastqc[:1]+["-Dfastqc.output_dir="+str(folder),"-Dfastqc.threads="+str(plan["threads"]),"-Dfastqc.quiet=true"]+fastqc[1:]+plan["files"]
    else:
        args = [*fastqc, "--threads", str(plan["threads"]), "--outdir", str(folder), *plan["files"]]
    _run(args, folder, "fastqc")
    multi = [multiqc, "--outdir", str(folder), str(folder)]
    _run(multi, folder, "multiqc")
    report = folder / "multiqc_report.html"
    if not report.is_file():
        raise ValueError("MultiQC 未产生 HTML 报告。")
    return _receipt(folder, {"report": str(report), "commands": [args,multi], "plan":plan})


@block("quantify")
def run_fastq(plan, outdir, progress=None, run_read_qc=False):
    binary, version = _cellranger()
    if not plan.get("reference_dir"):raise ValueError("定量需要一个已构建的参考索引。")
    plan = plan_fastq(**{k:v for k,v in plan.items() if k not in ("files","pairs")})
    folder = _dir(outdir)
    if run_read_qc:
        read_qc(plan, folder / "read_qc", progress)
    cmd = [binary,"count","--id=counts",f'--transcriptome={plan["reference_dir"]}',
           f'--fastqs={plan["fastq_dir"]}',f'--sample={plan["sample"]}',f'--chemistry={plan["chemistry"]}',
           f'--localcores={plan["threads"]}',f'--localmem={plan["memory_gb"]}',"--create-bam=false",
           f'--include-introns={str(plan["include_introns"]).lower()}']
    _report(progress, "Cell Ranger 正在按物理捕获定量")
    _run(cmd, folder, "count")
    outs = folder / "counts" / "outs"
    products = {"raw_path": "raw_feature_bc_matrix.h5", "filtered_path": "filtered_feature_bc_matrix.h5",
                "metrics_csv":"metrics_summary.csv", "summary_html":"web_summary.html"}
    if not all((outs / f).is_file() for f in products.values()):
        raise ValueError("Cell Ranger 输出缺失；请检查 count.log。")
    return _receipt(folder, {**{k:str(outs/v) for k,v in products.items()}, "version":version, "command":cmd,
                            "plan":plan, "input_sha256":{p:_file_sha(p) for p in plan["files"]},
                            "reference_metadata_sha256": _file_sha(Path(plan["reference_dir"])/"reference.json")})


def build_reference(fasta, gtf, outdir, *, name="plant_ref", threads=4, memory_gb=16):
    binary, version = _cellranger()
    _bounded_int(threads,"线程数",1,512)
    _bounded_int(memory_gb,"内存 GB",1,4096)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,60}",name):
        raise ValueError("参考名仅可含字母、数字、连字符和下划线。")
    fasta, gtf = [Path(p).resolve(strict=True) for p in (fasta,gtf)]
    folder = _dir(outdir)
    cmd = [binary,"mkref",f"--genome={name}",f"--fasta={fasta}",f"--genes={gtf}",
           f"--nthreads={threads}",f"--memgb={memory_gb}"]
    _run(cmd,folder,"mkref")
    result = folder / name
    if not (result/"reference.json").is_file() or not (result/"star"/"Genome").is_file():
        raise ValueError("生成的参考缺少 STAR 索引或 reference.json。")
    return _receipt(folder,{"reference_dir":str(result),"version":version,"command":cmd,
                            "source_sha256":{str(p):_file_sha(p) for p in (fasta,gtf)}})


def _component(folder, stem):
    paths = [folder / (stem + ext) for ext in (".gz", "") if (folder / (stem + ext)).is_file()]
    if len(paths) != 1:
        raise ValueError(f"10x MEX 需要唯一的 {stem} 或 {stem}.gz。")
    return paths[0]


def _tab(path):
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream, delimiter="\t"))


def _tenx(source):
    """Load genes × barcodes from one capture, preserving stable feature IDs."""
    import h5py
    import numpy as np
    from scipy import sparse
    from scipy.io import mmread
    p = Path(source).resolve(strict=True)
    if p.is_dir():
        fpath = (_component(p, "features.tsv") if any((p/(f"features.tsv{s}")).exists() for s in ("",".gz"))
                 else _component(p, "genes.tsv"))
        f = _tab(fpath); bars = _tab(_component(p,"barcodes.tsv"))
        if not all(len(row) >= 2 for row in f) or not all(len(row) == 1 for row in bars):
            raise ValueError("10x features/barcodes 列数错误。")
        features = [(r[0],r[1],r[2] if len(r)>2 else "Gene Expression") for r in f]
        barcodes = [r[0] for r in bars]
        matrix_file = _component(p,"matrix.mtx")
        with (gzip.open if matrix_file.suffix == ".gz" else open)(matrix_file,"rb") as stream:
            m = mmread(stream)
        if not sparse.issparse(m):
            raise ValueError("10x MEX 应使用稀疏坐标矩阵。")
        m = m.tocsc()
    elif p.suffix.lower() in (".h5", ".hdf5"):
        with h5py.File(p,"r") as fh:
            if "matrix/features" not in fh:
                raise ValueError("需要现代 10x GEX H5，其中应含 matrix/features。")
            grp = fh["matrix"]; fg = grp["features"]
            features = list(zip(fg["id"].asstr()[...],fg["name"].asstr()[...],fg["feature_type"].asstr()[...]))
            barcodes = list(grp["barcodes"].asstr()[...])
            m = sparse.csc_matrix((grp["data"][...],grp["indices"][...],grp["indptr"][...]),shape=tuple(grp["shape"][...]))
    else:
        raise ValueError("液滴与环境 RNA 工具接受 10x MEX 目录或 10x GEX H5。")
    if m.shape != (len(features),len(barcodes)) or len(set(barcodes)) != len(barcodes) or any(not x for x in barcodes):
        raise ValueError("条码重复/空白，或矩阵与细胞、基因轴不匹配。")
    keep = [i for i,row in enumerate(features) if row[2] == "Gene Expression"]
    if not keep:
        raise ValueError("矩阵缺少 Gene Expression。")
    if len(keep) != len(features):
        features = [features[i] for i in keep]; m = m[keep,:].tocsc()
    gen = [r[0] for r in features]
    if len(set(gen)) != len(gen) or any(not x for x in gen):
        raise ValueError("基因 ID 重复或为空。")
    if not np.isfinite(m.data).all() or (m.data < 0).any() or not np.equal(m.data,np.floor(m.data)).all():
        raise ValueError("此步骤需要未校正的非负整数 UMI 计数。")
    m.sum_duplicates()
    return m,features,barcodes


def _write_mex(folder, m, genes, bars):
    from scipy.io import mmwrite
    folder.mkdir()
    for name, rows in (("features.tsv.gz",genes),("barcodes.tsv.gz",([b] for b in bars))):
        with gzip.open(folder/name,"wt",encoding="utf-8",newline="") as stream:
            csv.writer(stream,delimiter="\t",lineterminator="\n").writerows(rows)
    with gzip.open(folder/"matrix.mtx.gz","wb") as stream:
        mmwrite(stream,m, symmetry="general")


def _r(package, script, args, folder):
    binary = _rscript()
    linux=PROJECT/".runtime"/"soupx-linux"
    wsl_soup=package=="SoupX" and os.name=="nt" and (linux/"runtime.json").is_file()
    if not binary and not wsl_soup:
        raise RuntimeError(f"需要在计算端安装 Rscript 和 R 包 {package}。")
    # Windows Rscript can translate non-ASCII absolute argv paths in a system code page.
    # All R artifacts are in the job directory. Launch from there with exact relative names.
    shutil.copyfile(R_SCRIPTS/script,folder/script)
    argv=[os.path.relpath(str(a),folder) if Path(str(a)).is_absolute() else str(a) for a in args]
    cmd = [binary,"--vanilla",script,*argv]
    if wsl_soup:
        from .starsolo import linux_path
        prefix=json.loads((linux/"runtime.json").read_text(encoding="utf-8"))["prefix"]
        cmd=["wsl.exe","--cd",linux_path(folder),"-e",linux_path(linux/"micromamba"),"run","-p",prefix,
             "Rscript","--vanilla",script,*[a.replace(os.sep,"/") for a in argv]]
    _run(cmd, folder, Path(script).stem, env=_r_env())
    return cmd


@block("call")
def call_droplets(raw_path, outdir, *, fdr=.01, lower=100, seed=42, niters=10000):
    import numpy as np
    from scipy.io import mmwrite
    _bounded_int(lower,"背景 UMI 上界",1,1000000)
    _bounded_int(seed,"随机种子",0,2147483647)
    _bounded_int(niters,"模拟次数",100,1000000)
    if not isinstance(fdr,(int,float)) or not 0 < fdr < 1:
        raise ValueError("FDR 应在 0 与 1 之间。")
    m, genes, bars = _tenx(raw_path)
    totals = np.asarray(m.sum(axis=0)).ravel()
    if not ((totals > 0) & (totals <= lower)).any() or not (totals > lower).any():
        raise ValueError("原始液滴矩阵需要同时有背景条码和高于 lower 的候选条码，当前阈值不满足。")
    folder = _dir(outdir); tsv = folder / "droplet_calls.tsv"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        mtx=Path(tmp)/"raw.mtx"
        with mtx.open("wb") as stream:
            mmwrite(stream, m, symmetry="general")
        cmd = _r("DropletUtils","emptydrops.R",[mtx,lower,fdr,seed,niters,Path(tmp)/"calls.tsv",folder/"r_versions.txt"],folder)
        keep=[]
        with (Path(tmp)/"calls.tsv").open(encoding="utf-8") as inp, tsv.open("w",encoding="utf-8",newline="") as out:
            rr=csv.DictReader(inp,delimiter="\t")
            wr=csv.writer(out,delimiter="\t",lineterminator="\n")
            wr.writerow(["barcode","total","pvalue","fdr","limited","kept"])
            n=0
            for n,row in enumerate(rr,1):
                if n>len(bars):
                    raise ValueError("emptyDrops 输出条码维度错误。")
                selected=row["kept"]=="TRUE"
                if selected:
                    keep.append(n-1)
                wr.writerow([bars[n-1],row["total"],row["pvalue"],row["fdr"],row["limited"],int(selected)])
            if n!=len(bars):
                raise ValueError("emptyDrops 输出条码数不匹配。")
    if not keep:
        raise ValueError("emptyDrops 未在指定 FDR 下检出有效条码；已保存全部诊断，请复核背景和输入。")
    filtered=folder/"filtered_feature_bc_matrix"
    _write_mex(filtered,m[:,keep],genes,[bars[i] for i in keep])
    return _receipt(folder,{"filtered_path":str(filtered),"raw_path":str(Path(raw_path).resolve()),
                            "barcodes_tsv":str(tsv),"kept":len(keep),"total":len(bars),
                            "params":{"lower":lower,"fdr":fdr,"seed":seed,"niters":niters},
                            "r_script_sha256":_file_sha(R_SCRIPTS/"emptydrops.R"),"command":cmd})


@block("ambient")
def correct_ambient(raw_path, filtered_path, clusters_tsv, outdir, *, rho=None):
    import numpy as np
    from scipy.io import mmread, mmwrite
    raw,rg,rb = _tenx(raw_path); filt,fg,fb = _tenx(filtered_path)
    if [g[0] for g in rg] != [g[0] for g in fg]:
        raise ValueError("raw 和 filtered 稳定基因 ID 或顺序不匹配。")
    ix={b:i for i,b in enumerate(rb)}
    if len(fb)>=len(rb) or any(b not in ix for b in fb):
        raise ValueError("filtered 条码必须是同一捕获 raw 条码的真子集。")
    if (raw[:,[ix[b] for b in fb]] != filt).nnz:
        raise ValueError("同名条码在 raw 和 filtered 中的原始计数不同。")
    cluster_rows = _tab(Path(clusters_tsv))
    if not cluster_rows or not {"barcode","cluster"}.issubset(cluster_rows[0]):
        raise ValueError("请提供按捕获匹配的 barcode / cluster 两列 TSV。")
    bi=cluster_rows[0].index("barcode"); ci=cluster_rows[0].index("cluster")
    labels={}
    for row in cluster_rows[1:]:
        if len(row)<=max(bi,ci) or not row[ci] or row[bi] in labels:
            raise ValueError("聚类文件存在缺失或重复条码。")
        labels[row[bi]]=row[ci]
    if set(labels)!=set(fb):
        raise ValueError("粗聚类文件与筛选条码集合不一致。")
    if rho is None and len(set(labels.values()))<2:
        raise ValueError("自动估计 SoupX 需要可信的多群体粗聚类。")
    if rho is not None and not (isinstance(rho,(int,float)) and 0 < rho < 1):
        raise ValueError("手动污染率 rho 应在 0 与 1 之间。")
    folder = _dir(outdir)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        tmp = Path(tmp)
        for name, matrix in (("raw",raw),("filtered",filt)):
            with (tmp/f"{name}.mtx").open("wb") as stream:
                mmwrite(stream, matrix, symmetry="general")
        # R operates on synthetic unique axis keys to avoid feature-name sanitisation.
        (tmp/"indexes.txt").write_text("\n".join(str(ix[b]+1) for b in fb),encoding="ascii")
        with (tmp/"clusters.txt").open("w",encoding="utf-8",newline="") as cl:
            cl.writelines(labels[b]+"\n" for b in fb)
        cmd = _r("SoupX","soupx.R",[tmp,"auto" if rho is None else rho,folder/"rho.txt",folder/"r_versions.txt"],folder)
        with (tmp/"corrected.mtx").open("rb") as stream:
            corrected=mmread(stream).tocsc()
        if corrected.shape!=filt.shape or not np.isfinite(corrected.data).all() or (corrected.data<0).any():
            raise ValueError("SoupX 修正矩阵无效。")
        target = folder/"corrected_feature_bc_matrix"
        _write_mex(target,corrected,fg,fb)
    return _receipt(folder,{"corrected_path":str(target),"raw_path":str(Path(raw_path).resolve()),
                            "filtered_path":str(Path(filtered_path).resolve()),"counts_semantics":"fractional_corrected",
                            "raw_total":float(filt.sum()),"corrected_total":float(corrected.sum()),
                            "rho_mode":"auto" if rho is None else "manual","rho":float((folder/"rho.txt").read_text().strip()),
                            "clusters_sha256":_file_sha(clusters_tsv),
                            "r_script_sha256":_file_sha(R_SCRIPTS/"soupx.R"),"command":cmd})
