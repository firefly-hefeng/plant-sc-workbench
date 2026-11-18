"""Prepare verified Arabidopsis TAIR10-62 quantification resources on a new installation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.starsolo import ASSETS,index_assets

def digest(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def prepare(threads=4,memory=16):
    manifest=json.loads((ROOT/"resources"/"quantification-sources.json").read_text(encoding="utf-8"))
    ASSETS.mkdir(exist_ok=True,parents=True)
    with tempfile.TemporaryDirectory(dir=ASSETS,prefix="prepare-") as tmp:
        staging=Path(tmp)
        for row in manifest:
            dest=ASSETS/row["name"]
            if not dest.exists():
                candidate=staging/dest.name
                with urlopen(row["url"],timeout=120) as src,candidate.open("wb") as out:
                    shutil.copyfileobj(src,out)
                if digest(candidate)!=row["sha256"]:raise ValueError("下载文件校验失败："+dest.name)
                candidate.replace(dest)
            elif digest(dest)!=row["sha256"]:
                raise ValueError("现有参考文件与登记版本不符："+str(dest))
            if dest.suffix==".gz":
                plain=dest.with_suffix("")
                candidate=staging/plain.name
                with gzip.open(dest,"rb") as src,candidate.open("wb") as out:shutil.copyfileobj(src,out)
                if plain.exists():
                    if digest(plain)!=digest(candidate):raise ValueError("既有解压文件与来源不一致："+plain.name)
                else:candidate.replace(plain)
        (ASSETS/"STAR").chmod(0o755)
        idx=ASSETS/"TAIR10-62-index"
        required=("Genome","SA","SAindex","genomeParameters.txt","index-source.json")
        if idx.exists():
            if not all((idx/name).is_file() for name in required):raise ValueError("既有索引目录不完整："+str(idx))
            info=json.loads((idx/"index-source.json").read_text(encoding="utf-8"))
            if info["fasta_sha256"]!=digest(ASSETS/"TAIR10.fa") or info["gtf_sha256"]!=digest(ASSETS/"TAIR10.62.gtf"):
                raise ValueError("索引来源与锁定参考不匹配")
        else:
            built=staging/"index"
            info=index_assets(ASSETS/"TAIR10.fa",ASSETS/"TAIR10.62.gtf",built,threads,memory)
            info["reference_dir"]=str(idx)
            (built/"index-source.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")
            built.rename(idx)
    print(idx)
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads",type=int,default=4)
    parser.add_argument("--memory-gb",type=int,default=16)
    args=parser.parse_args()
    prepare(args.threads,args.memory_gb)

