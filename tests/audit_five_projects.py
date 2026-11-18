"""Independent checks of completed scenario artifacts, including negative inputs and project isolation."""
from pathlib import Path
import json
from urllib.error import HTTPError
from zipfile import ZipFile
import anndata as ad
import pandas as pd
from five_project_study import api, read, write, hashfile, STUDY

def main():
    cases={p.parent.name:read(p) for p in STUDY.glob("*/实验记录.json")}
    assert len(cases)==5 and all(r["state"]=="passed" for r in cases.values())
    assert len({r["project"] for r in cases.values()})==5
    file_cache={}
    audit={"projects":{}, "checks":{}}
    def out(key):return STUDY/key/"runs"/cases[key]["show_job"]/"results"
    for key,case in cases.items():
        result={"successful":0,"expected_rejections":0,"receipt_entries":0}
        for task in case["jobs"].values():
            folder=STUDY/key/"runs"/task["id"]/"results"
            current=api("jobs/"+task["id"])
            assert current["project"]==case["project"] and current["state"]==task["state"]
            if task.get("expected_rejection"):
                assert current["state"]=="failed" and not (folder/"receipt.json").exists()
                result["expected_rejections"]+=1
                continue
            assert current["state"]=="succeeded"
            r=read(folder/"receipt.json")
            actual={p.resolve() for f in (folder,folder.parent/"intermediate") if f.is_dir() for p in f.rglob("*") if p.is_file() and p!=folder/"receipt.json"}
            assert actual=={Path(row["path"]).resolve() for row in r["outputs"]}
            for record in [*r["inputs"],*r["outputs"]]:
                p=Path(record["path"]).resolve()
                if p not in file_cache:file_cache[p]=(p.stat().st_size,hashfile(p))
                assert file_cache[p]==(record["bytes"],record["sha256"]),p
            result["successful"]+=1;result["receipt_entries"]+=len(r["outputs"])
        audit["projects"][key]=result

    c=cases["01"]
    spec=read(STUDY/"01"/next(iter(c["jobs"].values()))["form"])
    serial=api("qc-preview",{**spec,"params":{"min_counts":1400,"doublet_mode":"off"}})
    table=pd.read_csv(out("01")/"qc_cells.tsv",sep="\t")
    survivors=int((table.retained&(table.total_counts>=1400)).sum())
    assert serial["retained_cells"]==survivors and 0<survivors<1200
    audit["checks"]["单核提高阈值"]={"min_counts":1400,"expected":survivors,"preview":serial["retained_cells"]}
    qcs=read(out("02")/"summary.json")
    for i,row in enumerate(qcs["libraries"],1):
        assert len(pd.read_csv(out("02")/"captures"/f"{i:03d}"/"qc.tsv",sep="\t"))==row["input_cells"]
    audit["checks"]["叶片每捕获完整质控表"]=True
    reads={}
    for zipfile in sorted(out("03").rglob("*fastqc.zip")):
        with ZipFile(zipfile) as z:
            lines=z.read(next(p for p in z.namelist() if p.endswith("/fastqc_data.txt"))).decode().splitlines()
        stats=dict(line.split("\t",1) for line in lines if "\t" in line and not line.startswith("#"))
        reads[stats["Filename"]]={"reads":int(stats["Total Sequences"]),"length":stats["Sequence length"]}
    assert len(reads)==2 and all(r["reads"]==1000000 for r in reads.values()) and any(r["length"]=="26" for r in reads.values())
    audit["checks"]["FastQC 独立核对配对数量与读长"]=reads
    raw=read(out("04")/"receipt.json");filtered=next(s["filtered_path"] for s in raw["upstream"] if s["component"]=="call")
    spec=dict(project=cases["04"]["project"],action="analysis",libraries=[dict(id="no_background",kind="matrix",path=filtered)],params={"ambient_mode":"soupx"})
    refused=api("recipe",spec);block=next(b for b in refused["blocks"] if b["id"]=="ambient")
    assert not refused["ready"] and block["issues"]
    audit["checks"]["无背景液滴时阻止 SoupX"]=block["issues"]
    s=read(out("05")/"summary.json")
    obj=ad.read_h5ad(out("05")/"analysis.h5ad",backed="r")
    try:
        for r in s["libraries"]:
            for compartment,col in (("mito","mito_pct"),("plastid","plastid_pct")):
                assert r["matched_genes"][compartment]["genes_measured"]==0
                assert obj.obs.loc[obj.obs.capture==r["id"],col].isna().all()
                assert any(r["id"] in line and compartment in line for line in s["warnings"])
    finally:obj.file.close()
    audit["checks"]["玉米细胞器零匹配保留缺失值与警告"]=True
    try:api("plots?project="+cases["01"]["project"]+"&job="+cases["05"]["show_job"])
    except HTTPError as err:assert err.code==400
    else:raise AssertionError("cross-project use accepted")
    audit["checks"]["跨项目图表访问被拒绝"]=True
    audit.update(unique_verified_files=len(file_cache),bytes_verified=sum(size for size,_ in file_cache.values()))
    write(STUDY/"独立复核.json",audit)
    print(json.dumps(audit,ensure_ascii=False))
if __name__=="__main__":main()

