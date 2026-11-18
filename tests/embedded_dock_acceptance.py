"""Exercise file browsing, preview and parent selection through the real analysis pages."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from stage_workflow_acceptance import ROOT, BASE, api, run_job, wait_job, sync_playwright

def same_page(page,project,step):
    url=urlsplit(page.url)
    query=parse_qs(url.query)
    assert url.path=="/" and query["project"]==[project] and query["step"]==[str(step)],page.url

def scene(page,step):
    page.locator(f'.step-link[data-step="{step}"]').click()
    page.locator("#workDock .dock-grid").wait_for()

def bind(page,job,module):
    page.locator("#singleModule").select_option(module)
    page.locator('[data-act="choose-upstream"][data-kind=module]').click()
    page.locator("#handoffSource").select_option(job)
    page.locator(f'#handoffItems [data-source-job="{job}"]').click()
    page.wait_for_function("job=>document.querySelector('#componentParent')?.value===job",arg=job)
    assert page.locator("#stageMode").input_value()=="parent"

def main():
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    folder=ROOT/"validation/embedded-dock"/stamp;folder.mkdir(parents=True)
    project=api("projects",{"name":"步骤内分区验收 "+stamp,"path":str(folder/"project")})["id"]
    jobs={};checks={};errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge")
        page=browser.new_page(viewport={"width":1440,"height":960});page.set_default_timeout(18000)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(f"{BASE}/?project={project}&step=2")
        page.locator("#serverDot.ready").wait_for()
        for step in (1,2,3,4,5):
            scene(page,step);same_page(page,project,step)
            assert page.locator('#dockGrid').count()==1
            page.locator("#tab-upstream").click()
            page.locator("#handoffItems").get_by_text("暂无兼容的上游结果").wait_for()
        scene(page,2);page.locator("#tab-files").click()
        page.locator("details.stage-path summary").click()
        page.locator("#stagePath-counts").fill(str(ROOT/"validation/raw-adapters/tmpa5ko6sn3/filtered"))
        page.locator('[data-act=stage-path][data-role=counts]').click()
        page.locator("[data-stage-lib]:checked").wait_for()
        page.locator('[data-param=doublet_mode]').select_option("off")
        jobs["quality"]=run_job(page,"job-quality");wait_job(jobs["quality"])
        page.locator("#tab-stage").click()
        page.locator('[data-stage-artifact$="/qc.png"]').click()
        page.wait_for_function("document.querySelector('#dock-preview img')?.naturalWidth>0")
        same_page(page,project,2)
        assert not page.locator('#dock-preview [data-act=use-output]').count()
        page.locator("#tab-plots").click();page.locator("#plotJob").select_option(jobs["quality"])
        page.locator("#dockFigure").select_option("qc")
        page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0")
        page.locator('#dock-plots [data-act=open-output]').click()
        page.locator('#dock-files input#fileFilter').fill("qc_cells")
        page.locator('#fileRows [data-act=open-file][data-path$="/qc_cells.tsv"]').click()
        page.locator("#dock-preview table th").first.wait_for()
        page.screenshot(path=str(folder/"qc-table-and-plot.png"))
        same_page(page,project,2);page.reload()
        page.locator('#tab-preview[aria-selected=true]').wait_for()
        page.locator("#dock-preview table").wait_for()
        page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0")
        scene(page,3)
        page.locator('[data-param=hvg]').fill("210")
        page.locator('[data-param=hvg]').press("Tab")
        bind(page,jobs["quality"],"features")
        assert len(api("jobs?project="+project)["jobs"])==1
        assert page.locator('[data-param=hvg]').input_value()=="210"
        jobs["features"]=run_job(page,"job-single");wait_job(jobs["features"])
        bind(page,jobs["features"],"pca")
        jobs["pca"]=run_job(page,"job-single");wait_job(jobs["pca"])
        scene(page,4);bind(page,jobs["pca"],"graph")
        jobs["graph"]=run_job(page,"job-single");wait_job(jobs["graph"])
        page.locator("#singleModule").select_option("leiden")
        page.locator('[data-act=choose-upstream][data-kind=module]').click()
        page.locator("#handoffSource").select_option(jobs["graph"])
        page.locator('#handoffItems [data-act=open-output]').click()
        row=page.locator('#fileRows tr').filter(has=page.locator('[data-act=open-file][data-path$="/component.h5ad"]'))
        row.locator('[data-act=open-file]').click()
        page.locator(f'#dock-preview [data-source-job="{jobs["graph"]}"]').click()
        page.wait_for_function("id=>document.querySelector('#componentParent')?.value===id",arg=jobs["graph"])
        same_page(page,project,4)
        jobs["leiden"]=run_job(page,"job-single");wait_job(jobs["leiden"])
        page.locator("#tab-plots").click()
        page.locator("#plotJob").select_option(jobs["leiden"])
        page.locator("#partitionMount .barlayer").wait_for()
        page.locator('#tab-upstream').click()
        page.screenshot(path=str(folder/"cluster-handoff.png"))
        page.locator('[data-act=expand-workspace]').click()
        assert not page.locator("#workSettings").is_visible()
        page.locator("#dockDivider").focus();page.keyboard.press("ArrowRight")
        page.locator('[data-act=expand-workspace]').click()
        assert page.locator("#workSettings").is_visible()
        for action,parent in (("features","quality"),("pca","features"),("graph","pca"),("leiden","graph")):
            io=api(f'task-io?project={project}&job={jobs[action]}')
            assert io["parent_job"]==jobs[parent]
            path=Path(io["inputs"]["source"][0]["path"])
            assert path.is_relative_to(folder/"project/runs"/jobs[parent]/"results")
            with path.open("rb") as stream:digest=hashlib.file_digest(stream,"sha256").hexdigest()
            assert any(f["sha256"]==digest and f["path"]==str(path) for f in io["input_files"])
            checks[action]={"parent":jobs[parent],"source":path.name,"sha256":digest}
        page.goto(f"{BASE}/?project={project}&step=3")
        page.locator("#singleModule").select_option("pca")
        page.locator('#tab-upstream').click()
        assert jobs["quality"] not in page.locator('#handoffSource option').evaluate_all("(opts)=>opts.map(o=>o.value)")
        same_page(page,project,3)
        eligible=page.locator('#handoffSource option').evaluate_all("(opts)=>opts.map(o=>o.value)")
        assert set(eligible)<=set(jobs.values()) and all(api("jobs/"+j)["state"]=="succeeded" for j in eligible)
        # The action in an already-open preview must track the currently selected module.
        page.goto(BASE+f"/?project={project}&step=3&left=preview&preview=runs/{jobs['quality']}/results/qc.h5ad")
        page.locator("#singleModule").select_option("features")
        page.locator('#dock-preview [data-target=features]').wait_for()
        page.locator("#singleModule").select_option("pca")
        assert page.locator('#dock-preview [data-act=use-output]').count()==0
        ctx=browser.new_context(viewport={"width":390,"height":844});m=ctx.new_page()
        m.on("pageerror",lambda e:errors.append(str(e)))
        m.goto(f"{BASE}/?project={project}&step=4")
        m.locator('[data-act=focus-stage-files]').click();m.locator('#tab-stage[aria-selected=true]').wait_for()
        m.locator('[data-stage-artifact$="/cluster_comparison.tsv"]').click()
        m.locator("#dock-preview th").first.wait_for();same_page(m,project,4)
        m.screenshot(path=str(folder/"mobile-preview.png"))
        assert m.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors,errors
        browser.close()
    record=dict(project=project,jobs=jobs,bindings=checks,empty_stages=5,route_restored=True,errors=errors)
    (folder/"checks.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print(folder,record,flush=True)
if __name__=="__main__":main()

