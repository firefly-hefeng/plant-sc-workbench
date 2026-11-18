"""Run the five external H5AD entries in sequence, then compare the two graph bindings."""
import hashlib
import json
import sys
from pathlib import Path
import anndata as ad
import numpy as np
from sklearn.metrics import adjusted_rand_score
from stage_workflow_acceptance import api, wait_job

def main(directory):
    folder=Path(directory).resolve()
    info=json.loads((folder/"checks.json").read_text(encoding="utf-8"))
    jobs={}
    project=info["project"]
    runs=folder/"project/runs"
    source=runs/info["quality"]/"results/qc.h5ad"
    for action in ("features","pca","graph","umap","leiden"):
        if action=="leiden":source=runs/jobs["graph"]/"results/component.h5ad"
        form={"project":project,"action":action,"external_h5ad":str(source),"params":{"hvg":200,"n_pcs":12,"n_neighbors":10}}
        plan=api("recipe",form)
        assert plan["ready"],plan
        job=api("jobs",form)["id"];wait_job(job)
        io=api(f"task-io?project={project}&job={job}")
        assert io["inputs"]["source"][0]["path"]==str(source) and "parent" not in io["inputs"]
        with source.open("rb") as stream:digest=hashlib.file_digest(stream,"sha256").hexdigest()
        assert any(i["sha256"]==digest for i in io["input_files"])
        jobs[action]=job;source=runs/job/"results/component.h5ad"
    parent=api("jobs",{"project":project,"action":"leiden","parent_job":jobs["graph"]})["id"];wait_job(parent)
    external=ad.read_h5ad(source)
    direct=ad.read_h5ad(runs/parent/"results/component.h5ad")
    assert external.obs_names.equals(direct.obs_names)
    key="leiden"
    ari=float(adjusted_rand_score(external.obs[key],direct.obs[key]))
    assert ari==1 and np.array_equal(external.obs[key].astype(str),direct.obs[key].astype(str))
    data={"project":project,"jobs":jobs,"parent_path_leiden":parent,"ARI":ari,"exact_labels":True,
          "cells":external.n_obs,"genes":external.n_vars}
    (folder/"five-modules.json").write_text(json.dumps(data,indent=2),encoding="utf-8")
    print(data)
if __name__=="__main__":main(sys.argv[1])

