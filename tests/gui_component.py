"""Run a single stage from the visible workspace, inspect its receipt and figures."""
import json
from urllib.request import urlopen
from time import sleep
from pathlib import Path
from playwright.sync_api import sync_playwright
from workspace_jobs_acceptance import api, DEMO, ROOT

def main():
    base="http://127.0.0.1:8876"
    parent="0edaac4d3bf74cbd"
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge")
        page=browser.new_page(viewport={"width":1440,"height":960})
        errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(base+f"/?project={DEMO}&step=5")
        page.locator("#singleModule").select_option("umap")
        page.locator("#componentParent").select_option(parent)
        with page.expect_response(lambda r:r.url.endswith("/api/jobs") and r.request.method=="POST") as response:
            page.locator('[data-act="job-single"]').click()
        job=response.value.json()["id"]
        for _ in range(600):
            status=api("jobs/"+job)
            if status["state"] not in ("running","queued"):break
            sleep(1)
        assert status["state"]=="succeeded",status
        page.locator(f'[data-act="task-io"][data-id="{job}"]').click()
        page.get_by_text("下载完整接口清单").wait_for()
        page.locator('details.accordion summary').filter(has_text="二维嵌入").click()
        assert "obsm/X_umap" in page.locator(".accordion[open]").inner_text()
        assert parent in page.locator('dialog').inner_text()
        page.screenshot(path=str(ROOT/"validation/workspace-pages/component-io.png"))
        page.locator('[data-act="close"]').click()
        page.locator(f'[data-act="view-plots"][data-id="{job}"]').click()
        page.locator('#embeddingPlot .scatterlayer .points').first.wait_for(timeout=90000)
        assert page.locator('#embeddingPlot').evaluate('(el)=>el.data.reduce((n,t)=>n+t.x.length,0)')==1200
        assert not errors,errors
        browser.close()
    (ROOT/"lab-notebook/workspace-v2-gui-component.json").write_text(json.dumps(dict(parent=parent,job=job,action="umap",displayed_cells=1200,page_errors=errors),indent=2),encoding="utf-8")
if __name__=="__main__":main()

