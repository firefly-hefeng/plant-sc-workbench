"""Run against an existing workspace using an isolated Playwright browser context."""
import json,os,time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
HOST=os.environ.get("PLANT_TEST_URL","http://127.0.0.1:8876")
def main():
    previous=json.loads((ROOT/"lab-notebook/gui-run.json").read_text(encoding="utf-8"))
    pid=previous["project"];out=ROOT/"validation"/"browser";out.mkdir(exist_ok=True,parents=True)
    checks={};errors=[]
    with sync_playwright() as pw:
        b=pw.chromium.launch(channel="msedge",headless=True)
        page=b.new_page(viewport={"width":1440,"height":950},device_scale_factor=1)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(f"{HOST}/?project={pid}");page.locator("#serverStatus").filter(has_text="已连接").wait_for()
        page.screenshot(path=str(out/"workbench.png"),full_page=True)
        page.locator('[data-step="2"]').click();page.locator('[data-act="qc-preview"]').click()
        page.locator("#qcPreview").get_by_text("1,200",exact=False).first.wait_for(timeout=90000)
        checks["qc_preview"]=True
        page.locator('[data-step="5"]').click();page.locator('[data-act="inspect-recipe"]').click()
        page.locator("#dialogTitle").filter(has_text="本次执行模块").wait_for()
        checks["plan_modules"]=page.locator("#dialogBody .library-row").count()
        page.locator('[data-act="close"]').click()
        page.locator('[data-view="runs"]').click()
        page.locator('[data-act="open-output"]').first.click()
        page.locator('[data-act="gallery"]').click()
        page.locator('[data-act="open-file"][data-path$="embedding.png"]').click()
        page.wait_for_function("document.querySelector('#viewImage')?.naturalWidth > 0")
        page.locator('[data-act="zoom-in"]').click()
        checks["image_zoom"]=page.locator("#zoomValue").inner_text()
        page.screenshot(path=str(out/"viewer.png"),full_page=False)
        page.locator('[data-act="image-next"]').click()
        checks["image_next"]=page.locator("#dialogTitle").inner_text()
        page.locator('[data-act="close"]').click();page.locator('[data-act="list"]').click()
        page.locator('[data-act="open-file"][data-path$="/cluster_comparison.tsv"]').click()
        page.locator("#dialogBody th").first.wait_for()
        checks["table_headers"]=page.locator("#dialogBody th").all_inner_texts()
        page.locator('[data-act="close"]').click()
        page.locator('[data-view="work"]').click();page.locator('[data-step="4"]').click()
        page.locator('[data-param="resolutions"]').fill("0.45, 0.9")
        page.locator('[data-param="resolutions"]').press("Tab")
        with page.expect_response(lambda r:r.url.endswith("/api/jobs") and r.request.method=="POST") as ev:
            page.locator('[data-act="recluster"]').click()
        job=ev.value.json();assert job.get("id"),job
        checks["gui_recluster_job"]=job["id"]
        for _ in range(110):
            with urlopen(HOST+"/api/jobs/"+job["id"],timeout=5) as resp:row=json.load(resp)
            if row["state"] not in ("queued","running"):break
            time.sleep(1)
        assert row["state"]=="succeeded",row
        page.set_viewport_size({"width":390,"height":844});page.reload()
        page.wait_for_selector("#menuBtn",state="visible");page.locator("#menuBtn").click()
        page.locator('[data-step="2"]').click();checks["mobile_no_horizontal_overflow"]=page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(out/"mobile.png"))
        b.close()
    assert not errors,errors
    assert checks["mobile_no_horizontal_overflow"],checks
    (out/"acceptance.json").write_text(json.dumps({"project":pid,"checks":checks,"page_errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(checks,ensure_ascii=True))
if __name__=="__main__":main()

