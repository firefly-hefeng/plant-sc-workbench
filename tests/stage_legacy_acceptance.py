"""Read five archived projects and preview a quantification handoff without editing the archives."""
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:8876"
def main(destination):
    out=Path(destination)
    results={};errors=[]
    with sync_playwright() as pw:
        b=pw.chromium.launch(channel="msedge",headless=True)
        page=b.new_page(viewport={"width":1440,"height":960})
        page.on("pageerror",lambda e:errors.append(str(e)))
        writes=[]
        def capture(route):
            writes.append(route.request.post_data_json)
            route.fulfill(json={"saved":True})
        page.route("**/api/stage-settings",capture)
        for key,step in zip(("01","02","03","04","05"),(3,3,1,2,4)):
            case=json.loads((ROOT/"validation/five-projects"/key/"实验记录.json").read_text(encoding="utf-8"))
            pid,job=case["project"],case["show_job"]
            page.goto(BASE+"/?"+urlencode(dict(project=pid,step=step)))
            page.locator("#tab-stage").click()
            page.locator("#stageOutputJob").select_option(job)
            row=page.locator(f'[data-stage-artifact^="runs/{job}/"]').first
            row.wait_for()
            assert f"runs/{job}/" in row.get_attribute("data-stage-artifact")
            results[key]={"project":pid,"job":job,"step":step,"files":page.locator("[data-stage-artifact]").count()}
            page.locator("[data-stage-folder]").last.click()
            page.locator('#tab-files[aria-selected=true]').wait_for()
            page.locator('#tab-plots[aria-selected=true]').wait_for()
            assert job in page.url and "/panes" not in page.url and "step="+str(step) in page.url
        # The archive draft write is captured, the source and recipe services are live.
        pid=results["03"]["project"];job=results["03"]["job"]
        page.goto(BASE+f"/?project={pid}&step=2")
        page.locator('[data-act="choose-upstream"][data-kind=counts]').click()
        page.locator("#handoffSource").select_option(job)
        page.locator(f'#handoffItems [data-act=use-output][data-source-job="{job}"][data-capture="Flower"]').click()
        page.locator('[data-stage-lib]:checked').wait_for()
        page.locator('[data-step="5"]').click()
        assert page.locator('[data-stage-lib]').count()==2
        assert page.locator('[data-stage-lib]:checked').count()==1
        with page.expect_request(lambda r:r.url.endswith("/api/recipe")) as request:
            page.locator('[data-act="inspect-recipe"]').click()
        lib,=request.value.post_data_json["libraries"]
        assert lib["id"]=="Flower" and lib["sample"]=="SRR14574910" and lib["upstream_job"]==job
        assert Path(lib["path"]).is_dir() and Path(lib["filtered_path"]).is_dir()
        page.locator("dialog[open]").wait_for()
        page.locator('[data-act="close"]').click()
        page.locator('[data-stage-lib="Flower"]').click()
        assert page.locator('[data-stage-lib]:checked').count()==2
        page.locator('[data-act="inspect-recipe"]').click()
        page.locator('#toast').filter(has_text="同一捕获").wait_for()
        assert writes and not errors, errors
        results["quant_handoff"]={"capture":lib["id"],"sample":lib["sample"],"source_job":job,
                                   "paired_counts":True,"duplicate_prevented":True,"draft_write_intercepted":True}
        page.set_viewport_size({"width":390,"height":844})
        page.locator('[data-act="focus-stage-files"]').click()
        assert page.evaluate("document.activeElement.id==='stageFilePanel' && document.querySelector('#stageFilePanel').getBoundingClientRect().top < innerHeight")
        page.set_viewport_size({"width":1440,"height":960})
        page.goto(BASE+"/?project=6a2fc5fc7de64ab5&step=1")
        page.locator('#tab-upstream').click()
        page.locator('#handoffSource').select_option('9a6036f3f39145fd')
        index=page.locator('#handoffItems [data-act=use-output]')
        index.click()
        page.wait_for_function("document.querySelector('[data-param=star_index]').value.includes('9a6036f3f39145fd')")
        assert Path(page.locator('[data-param=star_index]').input_value(),'Genome').is_file()
        page.locator('[data-param=quantifier]').select_option('cellranger')
        page.locator('#handoffItems').get_by_text('此任务没有与当前用途和引擎匹配的产物。').wait_for()
        assert index.count()==0
        results['index_handoff']={'source':'9a6036f3f39145fd','exists':True,'wrong_engine_filtered':True}
        b.close()
    (out/"archived-pages.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(results)
if __name__=="__main__":main(sys.argv[1])

