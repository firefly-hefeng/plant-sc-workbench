"""Replay a result with its checked implementation. Usage: replay.py NEW_DIRECTORY [--from RESULT]."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def matches(file,digest):
    if not file.is_file():
        return False
    with file.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()==digest

def code_path(root,filename):
    return root/("resources/r" if filename.suffix==".R" else "backend")/filename.name

def archived_engine(here,root,dest,sources):
    engine=dest/"engine"
    (engine/"backend").mkdir(parents=True)
    shutil.copytree(root/"resources",engine/"resources")
    for entry in sources:
        filename=Path(entry["path"])
        archived=here/"code"/filename.name
        if not matches(archived,entry["sha256"]):
            raise ValueError("未找到与记录一致的归档组件："+filename.name)
        shutil.copyfile(archived,code_path(engine,filename))
    for stage in read(here/"receipt.json").get("upstream",[]):
        if "r_script_sha256" in stage:
            name="soupx.R" if "rho_mode" in stage else "emptydrops.R"
            if not matches(engine/"resources/r"/name,stage["r_script_sha256"]):
                raise ValueError("原运行所用的 R 组件版本无法还原："+name)
    # The historical Python implementation uses the runtime next to its source.
    # Keep external scientific runtimes in their original installation.
    runtime=(root/".runtime").resolve()
    if runtime.is_dir():
        alias=engine/".runtime"
        if os.name=="nt":
            env=dict(os.environ,PLANT_REPLAY_ALIAS=str(alias),PLANT_REPLAY_RUNTIME=str(runtime))
            subprocess.run(["powershell.exe","-NoProfile","-Command",
                            "New-Item -ItemType Junction -Path $env:PLANT_REPLAY_ALIAS -Target $env:PLANT_REPLAY_RUNTIME -ErrorAction Stop | Out-Null"],env=env,check=True)
        else:
            alias.symlink_to(runtime,target_is_directory=True)
        if not alias.samefile(runtime):
            raise ValueError("计算环境路径不一致")
    return engine

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination",type=Path)
    parser.add_argument("--from",dest="result",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    here=args.result.resolve()
    sources=read(here/"source-versions.json")
    root=Path(os.environ.get("PLANT_WORKBENCH_ROOT",Path(sources[0]["path"]).parents[1])).resolve()
    for entry in read(here/"inputs.json"):
        if not matches(Path(entry["path"]),entry["sha256"]):
            raise ValueError("输入文件版本已变化："+entry["path"])
    dest=args.destination.resolve()
    dest.mkdir(parents=True,exist_ok=False)
    current=all(matches(code_path(root,Path(e["path"])),e["sha256"]) for e in sources)
    execution_root=root if current else archived_engine(here,root,dest,sources)
    shutil.copyfile(here/"parameters.json",dest/"request.json")
    target_env=os.environ.copy()
    limits=read(here/"execution-environment.json").get("threads",{})
    target_env.update({k:v for k,v in limits.items() if v})
    subprocess.run([sys.executable,"-m","backend.worker",str(dest)],cwd=execution_root,env=target_env,check=True)
if __name__=="__main__":main()