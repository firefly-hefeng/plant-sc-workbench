"""Restore the independently locked SoupX worker on Windows with WSL."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.starsolo import linux_path

MAMBA="https://micro.mamba.pm/api/micromamba/linux-64/2.10.0"
SHA="701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd"
def wsl(args,**kwargs):
    return subprocess.run(["wsl.exe","-e",*args],check=True,**kwargs)
def main():
    directory=ROOT/".runtime"/"soupx-linux"
    directory.mkdir(parents=True,exist_ok=True)
    mamba=directory/"micromamba"
    if not mamba.exists():
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            download=Path(tmp)/"micromamba.tar.bz2"
            with urlopen(MAMBA,timeout=120) as src,download.open("wb") as dest:shutil.copyfileobj(src,dest)
            exe=Path(tmp)/"micromamba"
            with tarfile.open(download) as tar,exe.open("wb") as dest:shutil.copyfileobj(tar.extractfile("bin/micromamba"),dest)
            if hashlib.sha256(exe.read_bytes()).hexdigest()!=SHA:raise ValueError("Micromamba 下载校验失败")
            exe.replace(mamba)
        mamba.chmod(0o755)
    if hashlib.sha256(mamba.read_bytes()).hexdigest()!=SHA:raise ValueError("本地 Micromamba 版本不一致")
    binary=linux_path(mamba)
    home=wsl(["sh","-c",'printf "%s" "$HOME"'],capture_output=True,text=True).stdout
    base=home+"/.local/share/plant-sc-workbench";prefix=base+"/soupx-1.6.2"
    lock=ROOT/"lab-notebook"/"soupx-linux-lock.txt"
    wanted={s.strip() for s in lock.read_text(encoding="utf-8").splitlines() if s.startswith("https:")}
    exists=subprocess.run(["wsl.exe","-e","test","-d",prefix+"/conda-meta"]).returncode==0
    if not exists:
        wsl([binary,"create","-y","-r",base+"/mamba","-p",prefix,"-f",linux_path(lock)])
    installed=wsl([binary,"list","-p",prefix,"--explicit"],capture_output=True,text=True).stdout
    if {s.strip() for s in installed.splitlines() if s.startswith("https:")}!=wanted:
        raise ValueError("已有环境与登记包清单不同，请检查本机计算环境")
    result=wsl([binary,"run","-p",prefix,"Rscript","--vanilla","-e","library(SoupX);cat(as.character(packageVersion('SoupX')))"],capture_output=True,text=True)
    if result.stdout.strip()!="1.6.2":raise ValueError("SoupX 加载或版本检查失败")
    meta={"package":"SoupX","version":"1.6.2","backend":"WSL / conda-forge","prefix":prefix}
    (directory/"runtime.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    print(prefix)
if __name__=="__main__":main()

