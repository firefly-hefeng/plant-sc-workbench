"""Read stage inputs and publish one browser selection atomically on the local filesystem."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import csv
import json
import shutil

from .catalog import discover, absolute
from .inspection import recommendation
from .ports import SINGLE_MODULES
from .project_views import safe_name
from .workspace import child

LIBRARY_ROLES={"reads","counts","libraries"}
AUXILIARY={"fasta":(".fa",".fas",".fna",".fasta"),"gtf":(".gtf",),"whitelist":(".txt",".gz",".tsv"),
           "custom_reference":(".tsv",".json"),"clusters_tsv":(".tsv",)}


def describe(path, role, module=None, params=None):
    p=absolute(path)
    if role=="object":
        from .component_jobs import validate_slots
        if module not in SINGLE_MODULES or not p.is_file() or p.suffix.lower()!=".h5ad":
            raise ValueError("请选择当前计算模块和一个 H5AD 文件")
        slots=validate_slots(p,module,params or {},external=True)
        return {"path":str(p),"slots":slots}
    if role in AUXILIARY:
        if not p.is_file() or not p.name.lower().endswith(AUXILIARY[role]):
            raise ValueError("此输入需要 "+"/".join(AUXILIARY[role])+" 文件")
        if role=="custom_reference":
            from .resources import resolve_reference
            resolve_reference("custom",str(p))
        return {"path":str(p)}
    if role not in LIBRARY_ROLES:
        raise ValueError("未知的数据入口")
    if p.is_dir():
        # A sample sheet shipped beside its data preserves capture IDs and biological metadata.
        sheets=[]
        for candidate in p.iterdir():
            if candidate.is_file() and candidate.suffix.lower() in (".tsv",".csv") and candidate.stem.lower() not in ("barcodes","genes","features"):
                with candidate.open(encoding="utf-8-sig") as table:
                    header=table.readline(8192).rstrip("\r\n")
                if {"id","path"}<=set(next(csv.reader([header],delimiter="\t" if candidate.suffix.lower()==".tsv" else ","))):
                    sheets.append(candidate)
        if len(sheets)>1:raise ValueError("选区含多张样本表，请选择一张具体样本表")
    else:
        sheets=[]
    libs=discover(sheets[0] if sheets else p)
    if role!="libraries":
        libs=[l for l in libs if (l.get("kind")=="fastq")== (role=="reads")]
    if not libs:
        raise ValueError("此步骤需要成对的 10x FASTQ" if role=="reads" else "此步骤需要计数矩阵或文库样本表")
    for lib in libs:
        source=Path(lib["path"])
        if lib.get("kind")=="fastq":
            from .upstream import FASTQ_NAME
            pairs={}
            for read in source.glob("*.fastq.gz"):
                match=FASTQ_NAME.fullmatch(read.name)
                if match and match[1]==lib.get("prefix"):
                    pairs.setdefault((match[2],match[3],match[5]),set()).add(match[4])
            lib["input_files"]=sorted(read.name for read in source.glob("*.fastq.gz") if (match:=FASTQ_NAME.fullmatch(read.name)) and match[1]==lib.get("prefix"))
            if not pairs or any(reads!={"1","2"} for reads in pairs.values()):
                raise ValueError("FASTQ 文库缺少配套 R1/R2："+lib["id"])
        elif source.is_dir():
            from .qc import source_files
            lib["input_files"]=[entry.name for entry in source_files(source)]
        elif source.suffix.lower() in (".h5",".h5ad"):
            import h5py
            with h5py.File(source,"r") as handle:
                if source.suffix.lower()==".h5ad":
                    layer=lib.get("counts_layer") or ("counts" if "layers/counts" in handle else "X")
                    key="X" if layer=="X" else "layers/"+layer
                    if key not in handle or "var" not in handle or "obs" not in handle or (key=="X" and "uns/log1p" in handle):
                        raise ValueError("H5AD 需要有效的原始计数层和细胞、基因轴，可用样本表指定 counts_layer")
        else:
            raise ValueError("样本表中的文库需要计数矩阵或 FASTQ 目录")
    try:ref=recommendation(libs)
    except (KeyError,ValueError,OSError,TypeError):ref=None
    return {"path":str(p),"libraries":libs,"recommendation":ref,"recommended_reference":ref["id"] if ref else None}


def receive(store, query, stream, length):
    # A four-byte manifest length is followed by a UTF-8 file manifest and the file bytes.
    # Folder names are relative to the user's selection. No file is exposed before validation.
    project=store.project(query["project"])
    if length<5:raise ValueError("上传内容不完整")
    size=int.from_bytes(stream.read(4),"big")
    if not 0<size<=min(1024*1024,length-4):raise ValueError("上传清单长度无效")
    manifest=json.loads(stream.read(size).decode("utf-8"))
    if not isinstance(manifest,dict):raise ValueError("无效的文件清单")
    files=manifest.get("files")
    if not isinstance(files,list) or not files:raise ValueError("请选择文件或文件夹")
    entries=[]
    for row in files:
        if not isinstance(row,dict) or not isinstance(row.get("name"),str) or type(row.get("size"))!=int or row["size"]<0:
            raise ValueError("文件清单无效")
        parts=row["name"].split("/")
        if any(not s or s.startswith(".") or safe_name(s)!=s for s in parts):raise ValueError("无效的相对文件名")
        entries.append((Path(*parts),row["size"]))
    if len({str(p).casefold() for p,_ in entries})!=len(entries) or sum(n for _,n in entries)!=length-4-size:
        raise ValueError("有重名文件或文件大小不匹配")
    inbox=child(project["path"],"imports")
    inbox.mkdir(exist_ok=True)
    if sum(n for _,n in entries)>shutil.disk_usage(inbox).free:raise ValueError("项目磁盘可用空间不足")
    key=uuid4().hex[:16]
    with TemporaryDirectory(dir=inbox,prefix=".upload-") as temporary:
        # The data directory keeps the same name when promoted to the final location.
        bundle=Path(temporary)/key
        bundle.mkdir()
        for rel,amount in entries:
            target=bundle/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb") as dest:
                while amount:
                    chunk=stream.read(min(amount,1024*1024))
                    if not chunk:raise ValueError("上传中断，请重新选择文件")
                    dest.write(chunk);amount-=len(chunk)
        # For a single uploaded sample sheet, relative data paths must exist beside it.
        same_root=len({p.parts[0] for p,_ in entries})==1 and all(len(p.parts)>1 for p,_ in entries)
        chosen=bundle/entries[0][0] if len(entries)==1 else bundle/entries[0][0].parts[0] if same_root else bundle
        info=describe(chosen,query["role"],query.get("module"),manifest.get("params"))
        final=inbox/key
        def promote(path):
            path=Path(path)
            return str(final/path.relative_to(bundle)) if path.is_relative_to(bundle) else str(path)
        info["path"]=promote(info["path"])
        for lib in info.get("libraries",[]):
            if lib["id"]==key:
                lib["id"]="capture"
                if lib.get("sample")==key:lib["sample"]="capture"
            for field in ("path","filtered_path","raw_path","corrected_path","clusters_tsv"):
                if lib.get(field):lib[field]=promote(lib[field])
        bundle.rename(final)
    return {**info,"directory":final.relative_to(project["path"]).as_posix(),"files":len(entries)}

