"""Verify independent stages against the full published matrix run; verify three upstream actions."""
import json
import random
import time
from pathlib import Path
from urllib.error import HTTPError
from workspace_jobs_acceptance import api, DEMO, ROOT


def wait_for(job):
    for _ in range(900):
        result=api("jobs/"+job)
        if result["state"] not in ("queued","running"):
            assert result["state"]=="succeeded",result
            return result
        time.sleep(1)
    raise TimeoutError(job)


def main():
    seed_run=json.loads((ROOT/"lab-notebook/workspace-v2-jobs.json").read_text(encoding="utf-8"))["jobs"]
    qc=seed_run["standalone_qc"]["id"]
    try:
        api("recipe",dict(project=DEMO,action="umap",parent_job=qc))
    except HTTPError as exc:
        assert exc.code==400 and "connectivities" in exc.read().decode()
    else:
        raise AssertionError("source with no neighbor graph accepted")
    fast=json.loads((ROOT/"lab-notebook/fastq-job.json").read_text(encoding="utf-8"))["spec"]
    project=fast["project"]
    tasks={}
    for action in ("read_qc","quantify"):
        tasks[action]=api("jobs",{**fast,"action":action,"params":{**fast["params"],"run_read_qc":False}})["id"]
    assets=ROOT/"validation"/"workspace-pages"/"reference-fixture"
    assets.mkdir(exist_ok=True,parents=True)
    fasta=assets/"genome.fa"
    bases="".join(random.Random(811).choices("ACGT",k=64000))
    fasta.write_text(">fixture1\n"+"\n".join(bases[i:i+60] for i in range(0,len(bases),60))+"\n",encoding="ascii")
    gtf=assets/"features.gtf"
    gtf.write_text('fixture1\ttest\texon\t101\t401\t.\t+\t.\tgene_id "fixture"; transcript_id "tx1";\nfixture1\ttest\texon\t1001\t1401\t.\t+\t.\tgene_id "fixture"; transcript_id "tx1";\n',encoding="ascii")
    tasks["build_reference"]=api("jobs",dict(project=project,action="build_reference",params={"quantifier":"starsolo","fasta":str(fasta),"gtf":str(gtf),"threads":2}))["id"]
    chain={"features":qc}
    path={}
    for action in ("features","pca","graph","umap","leiden"):
        parent=chain[action]
        spec=dict(project=DEMO,action=action,parent_job=parent)
        assert [b["id"] for b in api("recipe",spec)["blocks"]]==[action,"export"]
        job=api("jobs",spec)["id"]
        wait_for(job)
        io=api(f"task-io?project={DEMO}&job={job}")
        assert [m["module"] for m in io["modules"]]==[action,"export"] and io["parent_job"]==parent
        path[action]=Path(io["outputs"]["component_object"][0]["path"])
        tasks[action]=job
        if action=="features":chain["pca"]=job
        if action=="pca":chain["graph"]=job
        if action=="graph":chain.update(umap=job,leiden=job)
    ids={}
    for action in ("read_qc","quantify","build_reference"):
        wait_for(tasks[action])
        io=api(f"task-io?project={project}&job={tasks[action]}")
        assert io["inputs"] and io["outputs"] and io["input_files"]
        ids[action]=[m["module"] for m in io["modules"]]
        if action=="quantify":
            names={Path(r["path"]).name for r in io["input_files"]}
            assert {"SA","SAindex","Genome","3M-february-2018.txt"}<=names
    import anndata as ad
    import numpy as np
    runs=ROOT/"workspace/花分生组织示例/runs"
    full=ad.read_h5ad(runs/seed_run["matrix"]["id"]/"results"/"analysis.h5ad")
    feature=ad.read_h5ad(path["features"])
    pca=ad.read_h5ad(path["pca"])
    graph=ad.read_h5ad(path["graph"])
    umap=ad.read_h5ad(path["umap"])
    leiden=ad.read_h5ad(path["leiden"])
    eq=dict(hvg=np.array_equal(full.var.highly_variable,feature.var.highly_variable),pca=np.array_equal(full.obsm["X_pca"],pca.obsm["X_pca"]),
            graph=(full.obsp["connectivities"]!=graph.obsp["connectivities"]).nnz==0,umap=np.array_equal(full.obsm["X_umap"],umap.obsm["X_umap"]),
            leiden=np.array_equal(full.obs.leiden,leiden.obs.leiden),counts=(full.layers["counts"]!=leiden.layers["counts"]).nnz==0,
            cell_axis=all(obj.obs_names.equals(full.obs_names) for obj in (feature,pca,graph,umap,leiden)))
    assert all(eq.values()),eq
    assert (graph.obsp["connectivities"]!=umap.obsp["connectivities"]).nnz==0 and (graph.obsp["connectivities"]!=leiden.obsp["connectivities"]).nnz==0
    assert "X_umap" not in leiden.obsm and "leiden" not in umap.obs and "connectivities" not in pca.obsp
    evidence=dict(jobs=tasks,upstream_modules=ids,branch_sources=chain,full_reference=seed_run["matrix"]["id"],
                  checkpoint=qc,equivalence=eq,missing_parent_graph_rejected=True,sibling_outputs_absent=True)
    (ROOT/"lab-notebook/workspace-v2-components.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print(evidence)
if __name__=="__main__":main()

