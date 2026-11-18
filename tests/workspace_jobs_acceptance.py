"""Exercise the live local service using explicitly registered demonstration inputs."""
import json
import time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
HOST="http://127.0.0.1:8876/api/"
DEMO="dceb6557e15b4b87"

def api(path,body=None):
    req=Request(HOST+path, data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    with urlopen(req,timeout=90) as response:return json.load(response)

def main():
    example=ROOT/"workspace/花分生组织示例/runs/0edaac4d3bf74cbd/form.json"
    default=json.loads(example.read_text(encoding="utf-8"))
    raw=json.loads((ROOT/"lab-notebook/raw-pipeline.json").read_text(encoding="utf-8"))["spec"]
    fast=json.loads((ROOT/"lab-notebook/fastq-job.json").read_text(encoding="utf-8"))["spec"]
    requests={"matrix":default,"raw":raw,"fastq":fast,"cancelled":dict(default,action="quality")}
    limit=api("queue")["limit"]
    assert limit==2 and not api("queue")["active"]
    jobs={key:api("jobs",spec)["id"] for key,spec in requests.items()}
    initial=api("queue")
    assert initial["active"]==2 and initial["waiting"]>=1,initial
    assert api("jobs/"+jobs["cancelled"]+"/cancel",{})["state"]=="cancelled"
    for key in ("standalone_qc","from_qc","recluster"):
        action={"standalone_qc":"quality","from_qc":"from_qc","recluster":"recluster"}[key]
        payload=dict(default,action=action) if action=="quality" else dict(project=DEMO,action=action,parent_job="eea0949b19c54cb1" if key=="from_qc" else "0edaac4d3bf74cbd")
        jobs[key]=api("jobs",payload)["id"]
    results={}
    deadline=time.monotonic()+900;peak=0
    while time.monotonic()<deadline:
        peak=max(peak,api("queue")["active"])
        for key,j in jobs.items():
            if key in results:continue
            status=api("jobs/"+j)
            if status["state"] in ("queued","running"):continue
            if key=="cancelled":assert status["state"]=="cancelled";results[key]=dict(id=j,state=status["state"]);continue
            assert status["state"]=="succeeded",(key,status)
            pid=status["project"];io=api(f"task-io?project={pid}&job={j}")
            assert io["schema"]=="plant-task-io/1" and io["inputs"] and io["outputs"] and io["modules"]
            plots=api(f"plots?project={pid}&job={j}")
            results[key]=dict(id=j,project=pid,state=status["state"],ports=[m["module"] for m in io["modules"]],figures=len(plots["items"]))
        if len(results)==len(jobs):break
        time.sleep(1)
    assert len(results)==len(jobs) and peak<=limit,(results,peak)
    try:api(f"task-io?project={DEMO}&job={jobs['raw']}")
    except HTTPError as exc:assert exc.code==400
    else:raise AssertionError("cross-project read accepted")
    import anndata as ad,numpy as np
    old=ad.read_h5ad(example.parent/"results"/"analysis.h5ad")
    new=ad.read_h5ad(example.parents[1]/jobs["matrix"]/"results"/"analysis.h5ad")
    old_graph=old.obsp["connectivities"].tocsr()
    new_graph=new.obsp["connectivities"].tocsr()
    assert np.array_equal(old_graph.indptr,new_graph.indptr) and np.array_equal(old_graph.indices,new_graph.indices)
    zeroed=(old_graph.data==0)&(new_graph.data>0)
    restored=int(zeroed.sum())
    assert restored==24 and np.array_equal(old_graph.data[~zeroed],new_graph.data[~zeroed]) and new_graph.data[zeroed].max()<.002
    equivalent={"counts":(old.layers["counts"]!=new.layers["counts"]).nnz==0,"barcodes":old.obs_names.equals(new.obs_names),
                "distances":(old.obsp["distances"]!=new.obsp["distances"]).nnz==0,"unchanged_graph_weights":True,"umap":np.array_equal(old.obsm["X_umap"],new.obsm["X_umap"]),"leiden":np.array_equal(old.obs.leiden,new.obs.leiden)}
    assert all(equivalent.values()),equivalent
    out=ROOT/"lab-notebook/workspace-v2-jobs.json"
    out.write_text(json.dumps(dict(limit=limit,initial=initial,peak=peak,jobs=results,equivalence=equivalent,restored_weak_weights=restored,maximum_restored_weight=float(new_graph.data[zeroed].max())),indent=2),encoding="utf-8")
    print(out)
if __name__=="__main__":main()

