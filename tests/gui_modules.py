"""Check no-code module handoff, QC summary, and round-trip parameter recipes."""
from pathlib import Path
import json,time,tempfile
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
HOST="http://127.0.0.1:8876"
def main():
    check=json.loads((ROOT/"lab-notebook/checkpoint-run.json").read_text(encoding="utf-8"))
    pid=check["project"]; errors=[];evidence={}
    with sync_playwright() as p,tempfile.TemporaryDirectory() as tmp:
        b=p.chromium.launch(channel="msedge",headless=True)
        page=b.new_page(viewport={"width":1440,"height":940},accept_downloads=True)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(HOST+"/?project="+pid)
        page.locator('[data-step="5"]').click()
        with page.expect_download() as download:page.locator('[data-act="export-recipe"]').click()
        recipe=Path(tmp)/"recipe.json";download.value.save_as(recipe)
        cfg=json.loads(recipe.read_text(encoding="utf-8"));assert cfg["schema"]=="plant-workbench/recipe-v1"
        with page.expect_file_chooser() as pick:page.locator('[data-act="import-recipe"]').click()
        pick.value.set_files(str(recipe))
        page.get_by_text("已载入配方，当前项目文库已保留。").wait_for()
        evidence["recipe_roundtrip"]=True
        page.locator('[data-step="3"]').click()
        page.locator("#qualityParent").select_option(check["parent"])
        with page.expect_response(lambda r:r.url.endswith("/api/jobs") and r.request.method=="POST") as sub:
            page.locator('[data-act="job-from_qc"]').click()
        job=sub.value.json()["id"]
        page.locator('[data-act="run-summary"][data-id="'+job+'"]').wait_for(timeout=180000)
        page.locator('[data-act="run-summary"][data-id="'+job+'"]').click()
        page.locator("#dialogBody table td").filter(has_text="GSM5320262").first.wait_for()
        evidence.update(parent=check["parent"],gui_continuation=job,qc_summary=True)
        page.screenshot(path=str(ROOT/"validation/browser/qc-summary.png"))
        page.locator('[data-act="close"]').click()
        page.locator('[data-act="view-embedding"][data-id="'+job+'"]').click()
        chart=page.locator("#embeddingPlot")
        chart.locator(".points").first.wait_for()
        page.wait_for_function("document.getElementById('embeddingPlot')?.data?.length>1")
        evidence["cluster_groups"]=chart.evaluate("(g)=>g.data.length")
        page.screenshot(path=str(ROOT/"validation/browser/cluster-explorer.png"))
        b.close()
    assert not errors,errors
    (ROOT/"lab-notebook/gui-modules.json").write_text(json.dumps({**evidence,"page_errors":errors},indent=2),encoding="utf-8")
    print(evidence)
if __name__=="__main__":main()

