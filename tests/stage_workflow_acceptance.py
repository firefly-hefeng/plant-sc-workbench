"""Exercise the visible stage inputs, native file chooser, task receipts, and persisted selections."""
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

import anndata as ad
from scipy import sparse
from sklearn.metrics import adjusted_rand_score
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.path.append(str(Path(sys.base_prefix)/"Lib"/"site-packages"))
    from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get("PLANT_TEST_URL","http://127.0.0.1:8876")
def api(url,data=None):
    req=Request(BASE+"/api/"+url,data=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type":"application/json"})
    with urlopen(req,timeout=120) as response:return json.load(response)
def run_job(page,action):
    with page.expect_response(lambda r:r.url.endswith("/api/jobs") and r.request.method=="POST",timeout=120000) as response:
        page.locator('[data-act="'+action+'"]').click()
    return response.value.json()["id"]
def wait_job(job):
    for _ in range(300):
        status=api("jobs/"+job)
        if status["state"] not in ("queued","running"):break
        time.sleep(1)
    assert status["state"]=="succeeded",status
def upload(page,role,paths,folder=False,ok=True):
    selector='[data-act="stage-upload'+('-folder' if folder else '')+'"][data-role="'+role+'"]'
    with page.expect_file_chooser() as chooser:page.locator(selector).click()
    with page.expect_response(lambda r:"/api/stage-upload?" in r.url,timeout=120000) as response:
        chooser.value.set_files(paths)
    res=response.value
    assert res.ok==ok,(res.status,res.text())
    if ok:page.locator('#toast').filter(has_text="已").wait_for()
    return res.json()

def main():
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    out=ROOT/"validation"/"stage-inputs"/stamp
    out.mkdir(parents=True)
    pid=api("projects",{"name":"工作位文件验收 "+stamp,"path":str(out/"project")})["id"]
    source=ROOT/"workspace/花分生组织示例/runs/96372e2a35bc47d9/results/analysis.h5ad"
    old=ad.read_h5ad(source)
    # Simulate an external graph handoff with no project metadata, labels, UMAP, PCs or distances.
    obj=ad.AnnData(X=sparse.csr_matrix((old.n_obs,1)),obs=old.obs[[]].copy())
    obj.obsp["connectivities"]=old.obsp["connectivities"].copy()
    graph=out/"flower-graph.h5ad";obj.write_h5ad(graph)
    mex=ROOT/"validation/raw-adapters/tmpa5ko6sn3/filtered"
    reads=ROOT/"validation/fastq-real-prefix"
    checks={};errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge",headless=True)
        ctx=browser.new_context(viewport={"width":1440,"height":960})
        page=ctx.new_page();page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(f"{BASE}/?project={pid}&step=0")
        page.locator('#serverStatus').filter(has_text="已连接").wait_for()
        assert page.locator("#workflowNav button").count()==5 and page.locator("h1").inner_text()=="质控与清洗"
        matrix=upload(page,"counts",[str(p) for p in mex.iterdir() if p.is_file()])
        page.locator('[data-param="doublet_mode"]').select_option("off")
        page.locator('[data-act="qc-preview"]').click();page.locator("#qcPreview th").first.wait_for(timeout=120000)
        qc=run_job(page,"job-quality")
        page.locator('[data-step="1"]').click()
        q=page.locator('[data-act="stage-path"][data-role="reads"]')
        page.locator(".stage-path summary").click();page.locator("#stagePath-reads").fill(str(reads));q.click()
        page.locator("#tab-stage").click()
        page.locator("#stageInputList").get_by_text("Flower_S1_L001_R1_001.fastq.gz",exact=False).wait_for()
        assert "capture" not in page.locator("#stageInputList").inner_text()
        page.locator('[data-step="4"]').click()
        page.locator("#singleModule").select_option("leiden")
        bad=upload(page,"object",str(ROOT/"examples/GSM5320262.h5ad"),ok=False)
        assert "connectivities" in bad["error"]
        bound=upload(page,"object",str(graph))
        page.locator(".stage-bound").filter(has_text=graph.name).wait_for()
        external=run_job(page,"job-single")
        assert "step=4" in page.url
        wait_job(qc);wait_job(external)
        page.locator("#tab-stage").click()
        page.locator('[data-stage-artifact$="cluster_comparison.tsv"]').click(timeout=30000)
        page.locator('#dock-preview th').filter(has_text="ARI").wait_for()
        page.screenshot(path=str(out/"clustering.png"))
        io=api(f"task-io?project={pid}&job={external}")
        digest=hashlib.sha256(graph.read_bytes()).hexdigest()
        assert "parent" not in io["inputs"] and io["inputs"]["source"][0]["path"]==bound["path"]
        assert any(f.get("sha256")==digest for f in io["input_files"])
        result=ad.read_h5ad(out/"project"/"runs"/external/"results/component.h5ad")
        assert result.obs_names.equals(old.obs_names)
        ari={k:float(adjusted_rand_score(old.obs[k],result.obs[k])) for k in ("leiden_0_5","leiden_1_0","leiden_seed_check")}
        assert min(ari.values())==1 and result.obs["sample"].unique().tolist()==["未登记"]
        page.locator("#tab-stage").click()
        page.locator('[data-input-folder]').click()
        page.locator('#fileRows').get_by_text(graph.name,exact=True).wait_for()
        page.locator('[data-step="2"]').click()
        page.locator("#tab-stage").click()
        page.locator('[data-stage-artifact$="qc.png"]').click()
        page.wait_for_function("document.querySelector('#dock-preview img')?.naturalWidth > 0")
        page.screenshot(path=str(out/"quality.png"))
        second=upload(page,"counts",str(mex),folder=True)
        page.locator('[data-stage-lib]').last.uncheck()
        page.locator('[data-step="5"]').click()
        assert page.locator('[data-stage-lib]:checked').count()==3
        page.locator('[data-stage-lib]').first.uncheck()
        page.wait_for_function("!document.querySelector('[data-stage-lib]').checked")
        page.wait_for_function("inputSaves.then(()=>true)")
        ctx.close()
        fresh=browser.new_context(viewport={"width":390,"height":844});page=fresh.new_page()
        page.goto(f"{BASE}/?project={pid}&step=2")
        page.locator('#serverStatus').filter(has_text="已连接").wait_for()
        assert page.locator('[data-stage-lib]:checked').count()==1
        assert page.locator('[data-stage-lib]').first.is_checked()
        page.screenshot(path=str(out/"mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.goto(f"{BASE}/?project={pid}&step=4")
        page.locator(".stage-bound").filter(has_text=graph.name).wait_for()
        assert page.locator("#singleModule").input_value()=="leiden"
        assert not errors,errors
        browser.close()
    checks.update(project=pid,quality=qc,leiden=external,nuclei=old.n_obs,ARI=ari,graph_sha256=digest,
                  multi_file=matrix["files"],folder=second["files"],missing_field=bad["error"],page_errors=errors)
    (out/"checks.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
    print(out, checks,flush=True)
if __name__=="__main__":main()

