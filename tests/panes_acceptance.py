"""Use the existing local Edge installation to exercise the two real tab groups."""
import json
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:8876"
OUT=ROOT/"validation/five-projects"
def main():
    cases={p.parent.name:json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("*/实验记录.json"))}
    assert len(cases)==5
    source=cases["01"];pid=source["project"];job=source["show_job"];path=f"runs/{job}/results"
    reports={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page(viewport={"width":1536,"height":960},device_scale_factor=1)
        errors=[];page.on("pageerror",lambda err:errors.append(str(err)))
        page.goto(BASE+"/?project="+pid)
        page.locator('button.nav[data-view="panes"]').click()
        page.locator('#tab-files[aria-selected=true]').wait_for()
        page.locator('#tab-plots[aria-selected=true]').wait_for()
        page.locator('#plotJob').select_option(job)
        page.wait_for_function("new URLSearchParams(location.search).get('job')==="+json.dumps(job))
        page.locator('#dock-plots [data-act="open-output"]').click()
        page.locator('#fileRows [data-path$="/qc_libraries.tsv"][data-act=open-file]').first.wait_for()
        page.locator('#dockFigure').select_option("umap")
        page.locator("#embeddingPlot .scatterlayer .point").first.wait_for()
        page.locator('#colorBy').select_option("capture")
        page.locator('#fileFilter').fill("qc_")
        page.locator('#fileRows [data-act=open-file][data-path$="/qc_libraries.tsv"]').first.click()
        page.locator('#dock-preview table').wait_for()
        assert page.locator('#tab-preview').get_attribute('aria-selected')=='true' and page.locator('#colorBy').input_value()=="capture"
        assert page.locator('#dock-preview').get_by_text("GSM5320262",exact=True).count()>=1
        page.locator('#tab-files').click()
        assert page.locator('#fileFilter').input_value()=="qc_"
        page.locator('#fileFilter').fill("")
        page.locator('#tab-jobs').click()
        page.locator('#dock-jobs [data-act="task-io"]').first.click()
        page.locator("dialog[open]").wait_for()
        page.locator('[data-act=close]').click()
        page.locator('#tab-plots').click()
        assert page.locator('#colorBy').input_value()=='capture'
        page.locator('#colorBy').select_option('leiden')
        page.locator('#dockDivider').focus()
        page.keyboard.press("ArrowRight")
        assert page.locator('#dockDivider').get_attribute('aria-valuenow')=='47'
        handle=page.locator('#dockDivider').bounding_box()
        page.mouse.move(handle["x"]+4,handle["y"]+30);page.mouse.down()
        page.mouse.move(handle["x"]+35,handle["y"]+30,steps=4);page.mouse.up()
        width=page.locator('#dockDivider').get_attribute('aria-valuenow');assert int(width)>47
        page.locator('[data-dock-focus="right"]').click()
        assert not page.locator('#group-left').is_visible()
        page.locator('[data-dock-focus="right"]').click()
        page.locator('#tab-preview').click()
        page.reload()
        page.locator('#dock-preview table').wait_for();page.locator("#embeddingPlot .scatterlayer .point").first.wait_for()
        assert page.locator('#dockDivider').get_attribute('aria-valuenow')==width and page.locator('#plotJob').input_value()==job
        page.locator('#tab-files').click()
        page.locator('#tab-files').focus();page.keyboard.press('ArrowRight')
        assert page.locator('#tab-preview').get_attribute('aria-selected')=='true'
        page.keyboard.press('ArrowLeft')
        page.locator('[data-dock-tree]').click()
        assert page.locator('#folderTree').is_visible()
        page.locator('[data-dock-tree]').click()
        page.screenshot(path=str(OUT/"分区桌面.png"))
        page.locator('#fileRows [data-act=open-file][data-path$="/pca.png"]').first.click()
        page.wait_for_function("document.querySelector('#dock-preview img')?.naturalWidth>0")
        page.locator('#dockFigure').select_option('cluster_comparison')
        page.wait_for_function("document.querySelector('#plotImage')?.naturalWidth>0")
        page.screenshot(path=str(OUT/"双图对照.png"))
        page.set_viewport_size({"width":390,"height":844})
        page.wait_for_function("document.querySelector('#rail').getBoundingClientRect().right<=1")
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        left=page.locator('#group-left').bounding_box();right=page.locator('#group-right').bounding_box()
        assert right["y"]>=left["y"]+left["height"] and not page.locator('#dockDivider').is_visible()
        page.screenshot(path=str(OUT/"分区窄屏.png"),full_page=True)
        page.set_viewport_size({"width":1536,"height":960})
        page.locator('#selectProject').click()
        page.locator('[data-act="activate-project"][data-id="'+cases["02"]["project"]+'"]').click()
        page.wait_for_function("new URLSearchParams(location.search).get('project')==="+json.dumps(cases["02"]["project"]))
        assert not page.locator('#dock-preview img').count() and page.locator('#tab-files').get_attribute('aria-selected')=='true'
        for key,case in cases.items():
            params={"project":case["project"],"job":case["show_job"],"path":"runs/"+case["show_job"]+"/results"}
            page.goto(BASE+"/panes?"+urlencode(params))
            page.locator('#fileRows').get_by_text("receipt.json",exact=True).wait_for()
            page.locator('#dockFigure option').first.wait_for(state="attached")
            assert page.locator('#plotJob').input_value()==case["show_job"]
            assert page.locator('#fileRows').get_by_text("receipt.json",exact=True).count()==1
            reports[key]={"job":case["show_job"],"figure_count":page.locator('#dockFigure option').count()}
        assert not errors,errors
        browser.close()
    record={"verified_projects":reports,"preview_preserves_plot":True,"tasks_preserve_files":True,"split_keyboard_and_drag":True,
            "focus_and_restore":True,"route_and_refresh":True,"project_isolation":True,"mobile_stacked":True,"page_errors":errors}
    (OUT/"分区交互验收.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":main()

