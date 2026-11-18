"""Verify real links, result switching and filesystem actions in a desktop browser."""
from pathlib import Path
import json,tempfile,sys
from uuid import uuid4
from urllib.request import urlopen,Request
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:8876"
PID="dceb6557e15b4b87"
JID="0edaac4d3bf74cbd"

def main():
    out=ROOT/"validation"/"workspace-pages";out.mkdir(parents=True,exist_ok=True)
    tmp=out/"manager-project";tmp.mkdir(exist_ok=True)
    source=tmp/"sample-note.txt";source.write_text("文件管理器测试\n",encoding="utf-8")
    payload=dict(name="文件管理器验收",path=str(tmp))
    req=Request(BASE+"/api/projects",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    testid=json.load(urlopen(req))["id"]
    key="复核-"+uuid4().hex[:6]
    errors=[];results={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page(viewport={"width":1450,"height":950})
        page.on("pageerror",lambda err:errors.append(str(err)))
        page.goto(BASE+"/files?project="+testid)
        page.locator("#fileRows").get_by_text("sample-note.txt").wait_for()
        page.locator('[data-act="mkdir-dialog"]').click()
        page.locator("#targetName").fill(key)
        page.locator('#fileActionForm [type="submit"]').click()
        page.locator('#folderTree .tree-title').get_by_text(key,exact=True).wait_for()
        page.locator('[data-act="copy-entry"][data-path="sample-note.txt"]').click()
        page.locator("#targetDirectory").fill(key);page.locator("#targetName").fill("副本.txt")
        page.locator('#fileActionForm [type="submit"]').click()
        page.locator('#fileRows [data-act="open-file"]').get_by_text("副本.txt",exact=True).wait_for()
        page.reload()
        page.locator("#fileRows").get_by_text("副本.txt",exact=True).wait_for()
        page.locator('[data-act="open-file"]').filter(has_text="副本.txt").click()
        assert "文件管理器测试" in page.locator(".preview-text").inner_text()
        assert (tmp/key/"副本.txt").read_bytes()==source.read_bytes()
        results["native_disk_create_and_copy"]=True
        page.locator('[data-act="close"]').click()
        page.goto(BASE+f"/files?project={PID}&path=runs/{JID}/results")
        page.locator("#fileRows").get_by_text("analysis.h5ad",exact=True).wait_for()
        page.locator('#fileOrder').select_option("size")
        page.screenshot(path=str(out/"files.png"))
        page.goto(BASE+f"/plots?project={PID}&job={JID}&figure=umap")
        page.locator('#embeddingPlot .scatterlayer .points').first.wait_for(timeout=90000)
        page.locator('#colorBy').select_option("sample")
        page.wait_for_function("document.querySelector('#embeddingPlot')?.data?.length===1")
        page.locator('#colorBy').select_option("leiden")
        page.wait_for_function("document.querySelector('#embeddingPlot')?.data?.length>1")
        page.screenshot(path=str(out/"plots.png"))
        page.locator('[data-act="select-plot"][data-figure="pca"]').click()
        page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0")
        assert "figure=pca" in page.url
        page.reload();page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0")
        page.locator('#plotJob').select_option("eea0949b19c54cb1")
        page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0 && location.search.includes('eea0949b19c54cb1')")
        assert page.locator('[data-figure="umap"]').count()==0
        page.go_back()
        page.wait_for_function("location.search.includes('figure=pca') && document.querySelector('#plotImage')?.naturalWidth>0")
        results["job_figure_reload_and_back"]=True
        page.set_viewport_size({"width":390,"height":844})
        page.wait_for_function("document.querySelector('#rail').getBoundingClientRect().right<=1")
        page.locator('#menuBtn').click()
        page.wait_for_function("document.querySelector('#rail').getBoundingClientRect().left>=-1")
        page.locator('#menuBtn').click()
        page.wait_for_function("document.querySelector('#rail').getBoundingClientRect().right<=1")
        results["mobile_menu_and_unobstructed_plot"]=True
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(out/"plots-mobile.png"))
        evidence=ROOT/"lab-notebook/workspace-v2-components.json"
        if evidence.is_file():
            job=json.loads(evidence.read_text(encoding="utf-8"))["jobs"]["leiden"]
            page.goto(BASE+f"/plots?project={PID}&job={job}&figure=partition-agreement")
            page.locator('#partitionMount .barlayer .point').first.wait_for()
            results["standalone_leiden_ari"]=True
        browser.close()
    assert not errors,errors
    (ROOT/"lab-notebook/workspace-v2-pages.json").write_text(json.dumps({**results,"page_errors":errors,"project":testid,"folder":key},ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":main()

