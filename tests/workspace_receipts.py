"""Recompute the checksums and required bindings of every completed acceptance route."""
import hashlib
import json
from pathlib import Path
from workspace_jobs_acceptance import ROOT, api, DEMO


def main():
    memo={}
    def verify(record):
        p=Path(record["path"]).resolve()
        if p not in memo:
            with p.open("rb") as f:
                memo[p]=(p.stat().st_size,hashlib.file_digest(f,"sha256").hexdigest())
        assert memo[p]==(record["bytes"],record["sha256"]),str(p)
    notes=ROOT/"lab-notebook"
    runs=json.loads((notes/"workspace-v2-jobs.json").read_text(encoding="utf-8"))["jobs"]
    cases={key:(r["project"],r["id"]) for key,r in runs.items() if r["state"]=="succeeded"}
    stages=json.loads((notes/"workspace-v2-components.json").read_text(encoding="utf-8"))["jobs"]
    for k,job in stages.items():
        cases[k]=(api("jobs/"+job)["project"],job)
    verified={}
    for k,(project,job) in cases.items():
        io=api(f"task-io?project={project}&job={job}")
        out=Path(io["project_path"])/"runs"/job/"results"
        receipt=json.loads((out/"receipt.json").read_text(encoding="utf-8"))
        for record in [*receipt["inputs"],*receipt["outputs"]]:
            verify(record)
        declared={Path(r["path"]).resolve() for r in receipt["outputs"]}
        actual={f.resolve() for folder in (out,out.parent/"intermediate") if folder.exists() for f in folder.rglob("*") if f.is_file() and f!=out/"receipt.json"}
        assert declared==actual,(job,declared.symmetric_difference(actual))
        verified[k]=dict(job=job,inputs=len(receipt["inputs"]),products=len(receipt["outputs"]),modules=[x["module"] for x in io["modules"]])
    report={"routes":verified,"unique_files_hashed":len(memo),"verified_bytes":sum(x[0] for x in memo.values())}
    (notes/"workspace-v2-integrity.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print({k:report[k] for k in ("unique_files_hashed","verified_bytes")})
if __name__=="__main__":main()

