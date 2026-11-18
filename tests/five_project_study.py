"""Live, repeatable five-project acceptance study. Each case records its own inputs, runs and assertions."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/"validation"/"five-projects"
BENCH=ROOT.parent/"plant-single-cell"/"bench-data"
API="http://127.0.0.1:8876/api/"
TITLES={"01":"花分生组织单核与检查点","02":"叶片双捕获与批次混杂","03":"短读段 FASTQ 定量","04":"背景液滴与环境 RNA","05":"玉米根尖多捕获分群"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path,data):
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    os.replace(temp,path)


def api(path,data=None):
    req=Request(API+path,data=None if data is None else json.dumps(data).encode(),headers={"Content-Type":"application/json"})
    with urlopen(req,timeout=120) as response:return json.load(response)


def hashfile(path):
    with open(path,"rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


class Project:
    def __init__(self,key):
        self.root=STUDY/key
        self.root.mkdir(parents=True,exist_ok=True)
        self.id=api("projects",{"name":"验证 "+key+" · "+TITLES[key],"path":str(self.root)})["id"]
        self.file=self.root/"实验记录.json"
        if self.file.exists():
            prior=read(self.file)
            previous_digest=hashfile(self.file)
            history=self.root/"历史实验记录"
            history.mkdir(exist_ok=True)
            snapshot=history/(previous_digest+".json")
            if not snapshot.exists():write(snapshot,prior)
        self.record={"case":key,"name":TITLES[key],"project":self.id,"started":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"jobs":{},"checks":{}}
        self.save()

    def save(self):
        write(self.file,self.record)

    def check(self,name,condition):
        self.record["checks"][name]=bool(condition)
        self.save()
        if not condition:raise AssertionError(name)

    def run(self,name,spec,expected_error=None):
        payload={**spec,"project":self.id}
        plan=api("recipe",payload)
        assert plan["ready"],plan
        j=api("jobs",payload)["id"]
        self.record["jobs"][name]={"id":j,"action":payload["action"],"form":"runs/"+j+"/form.json"}
        if expected_error:self.record["jobs"][name]["expected_rejection"]=expected_error
        self.save()
        until=time.monotonic()+1200
        while time.monotonic()<until:
            result=api("jobs/"+j)
            if result["state"] not in ("queued","running"):break
            time.sleep(1.2)
        else:raise TimeoutError(j)
        self.record["jobs"][name].update(state=result["state"],message=result["message"])
        self.save()
        if expected_error:
            self.check(name+" 预期拒绝",result["state"]=="failed" and expected_error in result["message"])
        else:
            self.check(name+" 成功",result["state"]=="succeeded")
            io=api(f"task-io?project={self.id}&job={j}")
            self.check(name+" 接口属于当前项目",io["project"]==self.id and io["job"]==j and bool(io["modules"]))
            self.record["jobs"][name]["modules"]=[m["module"] for m in io["modules"]]
        return j,self.root/"runs"/j/"results"


def lib(key,path,modality,species="Arabidopsis thaliana",**kwargs):
    return dict(id=key,sample=key,kind="matrix",path=str(path),modality=modality,species=species,**kwargs)


def flower(p):
    source=ROOT/"examples/GSM5320262.h5ad"
    p.record["materials"]={"accession":"GSM5320262","input_sha256":hashfile(source),"source":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM5320262"}
    spec=dict(libraries=[lib("GSM5320262",source,"snRNA")],reference="ath-tair10-62",action="quality")
    api("project-inputs",{**spec,"project":p.id})
    qc,qdir=p.run("冻结单核 QC",spec)
    analysis,adir=p.run("沿用条码继续",dict(action="from_qc",parent_job=qc))
    _,rdir=p.run("同图重分群",dict(action="recluster",parent_job=analysis,params={"resolutions":[0.35,0.85]}))
    q,a,r=[ad.read_h5ad(x) for x in (qdir/"qc.h5ad",adir/"analysis.h5ad",rdir/"analysis.h5ad")]
    p.check("核条码与整数计数沿用",q.n_obs==1200 and q.obs_names.equals(a.obs_names) and (q.X!=a.layers["counts"]).nnz==0)
    p.check("重分群沿用同图及坐标",a.obs_names.equals(r.obs_names) and (a.obsp["connectivities"]!=r.obsp["connectivities"]).nnz==0 and np.array_equal(a.obsm["X_umap"],r.obsm["X_umap"]))
    p.check("两档分辨率输出",{"leiden_0_35","leiden_0_85"}<=set(r.obs))
    p.record["metrics"]={"nuclei":a.n_obs,"genes":a.n_vars,"clusters_by_resolution":{k:int(r.obs[k].nunique()) for k in ("leiden_0_35","leiden_0_85")}}
    p.record["show_job"]=analysis


def leaf(p):
    libs=[]
    for k,condition in [("GSM8417227","Mild drought"),("GSM8417230","Well-watered")]:
        libs.append(lib(k,BENCH/"mainline-v1"/"staged"/"leaf_scrna"/(k+".h5ad"),"scRNA",batch=k,condition=condition))
    p.record["materials"]=[{"id":l["id"],"condition":l["condition"],"sha256":hashfile(l["path"]),"source":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc="+l["id"]} for l in libs]
    spec=dict(action="analysis",reference="ath-tair10-62",libraries=libs,params=dict(feature_join="intersection",integration="harmony",doublet_mode="report"))
    j,folder=p.run("按真实处理检查批次",spec)
    obj=ad.read_h5ad(folder/"analysis.h5ad")
    summary=read(folder/"summary.json");methods=summary["methods"]
    p.check("批次与处理混杂时回退 PCA",methods["integration"]["status"]=="ineligible" and methods["representation"]=="X_pca" and "X_pca_harmony" not in obj.obsm)
    measured={l["id"]:l for l in summary["libraries"]}
    p.check("保留两捕获及条件标签",set(measured)==set(obj.obs.capture.astype(str))=={l["id"] for l in libs} and set(obj.obs.condition.astype(str))=={l["condition"] for l in libs})
    p.check("交集损失与每捕获留存可查",all("discarded_counts_from_feature_join" in row and row["input_cells"]==1200 for row in measured.values()) and sum(row["retained_cells"] for row in measured.values())==obj.n_obs)
    p.record["metrics"]=dict(input_cells=summary["input_cells"],retained=obj.n_obs,shared_genes=obj.n_vars,representation=methods["representation"],capture_loss={k:r["discarded_counts_from_feature_join"] for k,r in measured.items()})
    p.record["show_job"]=j


def reads(p):
    spec=read(ROOT/"lab-notebook/fastq-job.json")["spec"]
    p.record["materials"]={"accession":"SRR14574910","pairs_in_archived_prefix":1000000,"source":"https://www.ncbi.nlm.nih.gov/sra/SRR14574910"}
    api("project-inputs",{**spec,"project":p.id})
    p.run("常规 v3 读长反例",{**spec,"action":"quantify","params":{"chemistry":"SC3Pv3","run_read_qc":False}},expected_error="至少 28 nt")
    j,out=p.run("短 UMI 定量与读段质检",{**spec,"action":"quantify","params":{"chemistry":"SC3Pv3_10","run_read_qc":True}})
    receipt=read(out/"receipt.json")
    quant=next(x for x in receipt["upstream"] if x["component"]=="quantify")
    reports=api(f"plots?project={p.id}&job={j}")["items"]
    p.check("读段配对及定量布局",len(quant["input_fastqs"])==2 and quant["umi_length"]==10 and quant["feature"]=="GeneFull")
    inputs={Path(row["path"]).name for row in receipt["inputs"]}
    p.check("白名单及索引被追踪",{"Genome","SAindex",Path(quant["whitelist"]).name}<=inputs)
    p.check("原始和过滤矩阵匹配",all((Path(quant[k])/"matrix.mtx").is_file() for k in ("raw_path","filtered_path")))
    def dim(path):
        with (Path(path)/"matrix.mtx").open() as stream:return [int(v) for v in next(l for l in stream if l.strip() and not l.startswith("%")).split()]
    raw,filtered=dim(quant["raw_path"]),dim(quant["filtered_path"])
    p.check("定量维度和报告",raw[0]==filtered[0] and raw[1]>=filtered[1]>0 and sum(i["kind"]=="report" for i in reports)>=3)
    p.record["metrics"]=dict(raw_matrix=raw,filtered_matrix=filtered,umi_nt=10,reports=len(reports))
    p.record["show_job"]=j


def ambient(p):
    spec=read(ROOT/"lab-notebook/raw-pipeline.json")["spec"]
    p.record["materials"]={"kind":"synthetic","seed":42,"positive_barcodes":"bc0..bc599","background_barcodes":"bc600..bc1899","simulated_ambient_fraction":0.06}
    j,folder=p.run("液滴调用与去污染",spec)
    receipt=read(folder/"receipt.json")
    call=next(r for r in receipt["upstream"] if r["component"]=="call")
    soup=next(r for r in receipt["upstream"] if r["component"]=="ambient")
    table=pd.read_csv(call["barcodes_tsv"],sep="\t")
    chosen=set(table.loc[table.kept.eq(1),"barcode"]);truth={"bc"+str(i) for i in range(600)}
    tp=len(chosen&truth);fp=len(chosen-truth)
    p.check("本夹具已知条码的检出与误收",len(table)==1900 and tp>=590 and fp<=10)
    a=ad.read_h5ad(folder/"analysis.h5ad")
    raw=a.layers["counts"];corrected=a.layers["soupx"]
    p.check("整数原始层与校正层独立",np.issubdtype(raw.dtype,np.integer) and raw.shape==corrected.shape and 0<float(corrected.sum())<float(raw.sum()))
    p.check("实际使用校正层",read(folder/"summary.json")["methods"]["analysis_layer"]=="soupx")
    p.record["metrics"]=dict(true_positive=tp,false_positive=fp,false_negative=600-tp,estimated_rho=soup["rho"],added_fraction=.06,retained=a.n_obs)
    p.record["show_job"]=j


def maize(p):
    staged=BENCH/"labelled-v3/staged/ortiz_2021_maize"
    src=staged/"counts.h5ad";a=ad.read_h5ad(src);libs=[]
    inputdir=p.root/"captures";inputdir.mkdir(exist_ok=True)
    for k,indices in a.obs.groupby("sample",observed=True).groups.items():
        f=inputdir/(k+".h5ad");part=a[indices].copy()
        if not f.exists():part.write_h5ad(f,compression="gzip")
        saved=ad.read_h5ad(f)
        assert saved.obs_names.equals(part.obs_names) and saved.var_names.equals(part.var_names) and (saved.X!=part.X).nnz==0
        libs.append(lib(k,f,"scRNA","Zea mays",condition="root meristem",batch=k))
    p.record["materials"]=dict(accession="GSE173087",source="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE173087",source_sha256=hashfile(src),samples={l["id"]:int((a.obs["sample"]==l["id"]).sum()) for l in libs})
    j,out=p.run("玉米参考与同条件多批次",dict(action="analysis",reference="zma-b73v4-48",libraries=libs,params=dict(integration="harmony",doublet_mode="report",resolutions=[.4,.8,1.2])))
    _,branch=p.run("独立 Leiden 分区",dict(action="leiden",parent_job=j,params={"resolutions":[.4,.8,1.2]}))
    obj=ad.read_h5ad(out/"analysis.h5ad");b=ad.read_h5ad(branch/"component.h5ad")
    s=read(out/"summary.json");method=s["methods"]["integration"]
    p.check("真实批次与校正表示",len(libs)==3 and method["status"]=="computed" and s["methods"]["representation"]=="X_pca_harmony" and np.isfinite(obj.obsm["X_pca_harmony"]).all())
    p.check("各捕获覆盖记录及样本构成",all(set(r["matched_genes"])=={"mito","plastid"} for r in s["libraries"]) and set(pd.read_csv(out/"cluster_samples.tsv",sep="\t",index_col=0).columns)=={l["id"] for l in libs})
    p.check("独立 Leiden 复用图和三套分区",(obj.obsp["connectivities"]!=b.obsp["connectivities"]).nnz==0 and all(np.array_equal(obj.obs[k],b.obs[k]) for k in ("leiden_0_4","leiden_0_8","leiden_1_2")))
    p.record["metrics"]=dict(input_cells=a.n_obs,retained=obj.n_obs,genes=obj.n_vars,groups=int(obj.obs.leiden.nunique()),neighbor_retention=method["neighbor_retention"],coverage={r["id"]:r["matched_genes"] for r in s["libraries"]})
    p.record["show_job"]=j


def study(key):
    p=Project(key)
    try:
        {"01":flower,"02":leaf,"03":reads,"04":ambient,"05":maize}[key](p)
        p.record["state"]="passed"
    except Exception as exc:
        p.record.update(state="failed",error=repr(exc))
        raise
    finally:
        p.record["ended"]=time.strftime("%Y-%m-%dT%H:%M:%S%z");p.save()
        print(key,p.record["state"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("cases",nargs="*",default=list(TITLES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(study,k) for k in parser.parse_args().cases]
        for future in concurrent.futures.as_completed(futures):future.result()

