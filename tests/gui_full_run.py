"""Submit a complete saved matrix recipe from the ordinary UI and exercise plotted results."""
from pathlib import Path
import json, time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
HOST="http://127.0.0.1:8876"
def main():
    original=json.loads((ROOT/"lab-notebook/gui-run.json").read_text(encoding="utf-8"))
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge")
        page=browser.new_page(viewport={"width":1440,"height":960})
        page.on("pageerror",lambda x:errors.append(str(x)))
        page.goto(HOST+"/?project="+original["project"])
        page.locator('[data-act="job-analysis"]').first.wait_for()
        with page.expect_response(lambda r:r.url.endswith("/api/jobs") and r.request.method=="POST") as result:
            page.locator('[data-act="job-analysis"]').first.click()
        job=result.value.json()
        with urlopen(HOST+"/api/jobs/"+job["id"]) as response:state=json.load(response)
        for _ in range(240):
            if state["state"] not in ("queued","running"):break
            time.sleep(1)
            with urlopen(HOST+"/api/jobs/"+job["id"]) as response:state=json.load(response)
        assert state["state"]=="succeeded",state
        page.locator('[data-act="view-embedding"][data-id="'+job["id"]+'"]').click()
        plot=page.locator("#embeddingPlot");plot.locator(".scatterlayer .points").first.wait_for()
        fields=page.locator("#colorBy option").evaluate_all("(els)=>els.map(x=>x.value)")
        page.locator("#colorBy").select_option("sample")
        page.wait_for_function("document.getElementById('embeddingPlot').data.length===1")
        plot.locator(".scatterlayer .point").first.dispatch_event("mouseover")
        page.screenshot(path=str(ROOT/"validation/browser/interactive-umap.png"))
        n=plot.evaluate("(el)=>el.data.reduce((s,t)=>s+t.x.length,0)")
        assert n==1200 and "capture" in fields and "leiden" in fields
        page.locator('[data-view="work"]').click()
        page.locator('[data-step="2"]').click()
        page.locator('[data-act="qc-preview"]').click()
        page.locator('#qcScatter .scatterlayer .point').first.wait_for(timeout=90000)
        page.screenshot(path=str(ROOT/"validation/browser/qc-preview.png"))
        browser.close()
    assert not errors,errors
    rec=dict(project=original["project"],job=job["id"],state=state["state"],fields=fields,
             displayed_cells=n,qc_scatter=True,page_errors=errors)
    (ROOT/"lab-notebook/workspace-v2-gui-run.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
    print(rec)
if __name__=="__main__":main()

