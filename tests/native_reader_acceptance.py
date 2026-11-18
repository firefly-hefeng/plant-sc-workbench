"""Read existing scientific reports and exercise synthetic files without submitting jobs."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import sys
import tempfile
from threading import Thread
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sys.path.append(str(Path(sys.base_prefix) / "Lib/site-packages"))
    from playwright.sync_api import sync_playwright, expect
from PIL import Image
from app import API, Handler
from backend.native_reports import report_service

BASE = os.environ.get("PLANT_TEST_URL", "http://127.0.0.1:8876")
EVIDENCE = ROOT / "validation/native-readers"
PROJECT, JOB = "d02e9770456b451d", "3798825899a84d19"
FIGDIR = "results/capture-001/read_qc/"


def page_url(base, view="/", **fields):
    return base + view + "?" + urlencode(fields)


def real_reports(page):
    path = FIGDIR + "Flower_S1_L001_R1_001_fastqc.html"
    url = page_url(BASE, project=PROJECT, job=JOB, step=2, preview="操作卡.md", figure=path)
    page.goto(url)
    card = page.locator("#dock-preview .native-markdown")
    expect(card.locator("h1")).to_contain_text("花分生组织")
    expect(card.locator("ol li")).to_have_count(5)
    expect(card.locator("table")).to_have_count(1)
    assert card.get_by_text("GEO 样本 GSM5320262").get_attribute("target") == "_blank"
    read_lengths = []
    for end in ("R1", "R2"):
        page.locator("#dockFigure").select_option(path.replace("R1", end))
        report = page.frame_locator("#dock-plots iframe")
        expect(report.locator("#header_filename")).to_contain_text(end)
        expect(report.get_by_text("Total Sequences", exact=True).locator("..")).to_contain_text("1000000")
        read_lengths.append(report.get_by_text("Sequence length", exact=True).locator("..").locator("td").last.inner_text())
        report.get_by_role("link", name="Per base sequence quality", exact=True).click()
        expect(report.locator("div.module").nth(1).locator("img.indented")).to_be_visible()
        assert report.locator("img.indented").first.evaluate("el=>el.naturalWidth>0")
        report.get_by_role("link", name="Basic Statistics", exact=True).click()
    assert read_lengths == ["26", "98"]
    page.locator("#dockFigure").select_option(path)
    expect(page.frame_locator("#dock-plots iframe").locator("#header_filename")).to_contain_text("R1")
    page.locator("[data-guide-step] summary").click()
    page.locator("#workDock").evaluate("el=>el.scrollIntoView({block:'nearest'})")
    page.screenshot(path=str(EVIDENCE / "质控同页阅读.png"))
    card.get_by_role("link", name="样本表.tsv").click()
    expect(page.locator("#dock-preview th", has_text="sample").first).to_be_visible()
    assert "step=2" in page.url
    page.reload()
    expect(page.locator("#dock-preview th", has_text="sample").first).to_be_visible()
    page.locator("#tab-files").click()
    page.reload()
    expect(page.locator("#tab-files")).to_have_attribute("aria-selected","true")
    page.locator("#tab-preview").click()
    expect(page.locator("#dock-preview th", has_text="sample").first).to_be_visible()
    page.locator("#dockFigure").select_option(FIGDIR + "multiqc_report.html")
    report = page.frame_locator("#dock-plots iframe")
    expect(report.locator(".js-plotly-plot").first).to_be_attached()
    button = report.get_by_role("button", name="Clustered", exact=True)
    button.click()
    expect(button).to_have_class(re.compile(r"\bactive\b"))
    plots = report.locator(".js-plotly-plot").count()
    assert plots > 0
    with page.expect_popup() as opened:
        page.locator("#dock-plots .native-expand").click()
    full = opened.value
    expect(full.locator(".js-plotly-plot").first).to_be_attached()
    assert urlsplit(full.url).port != urlsplit(BASE).port
    full.close()
    page.goto(page_url(BASE, "/plots", project="dceb6557e15b4b87", job="073c9a6d94dd4def", figure="results/report.html"))
    report = page.frame_locator(".gallery-report iframe")
    expect(report.get_by_role("heading", name="植物单细胞注释前分析")).to_be_visible()
    report.locator("img").last.evaluate("el=>el.decode()")
    widths = report.locator("img").evaluate_all("els=>els.map(el=>el.naturalWidth)")
    assert len(widths) == 2 and min(widths) > 0
    page.goto(page_url(BASE, "/files", project=PROJECT))
    page.locator('#fileRows [data-path="操作卡.md"]').first.click()
    expect(page.locator("#dialogBody .native-markdown h1")).to_be_visible()
    page.locator("#dialogBody").get_by_role("link", name="来源与校验.json").click()
    expect(page.locator("#dialogTitle")).to_have_text("来源与校验.json")
    expect(page.locator("#dialogBody pre")).to_contain_text("{")
    folder = "runs/" + JOB + "/results/capture-001/read_qc"
    page.goto(page_url(BASE, "/files", project=PROJECT, path=folder))
    page.locator('#fileRows [data-act=open-file][data-path$="_R1_001_fastqc.html"]').click()
    expect(page.frame_locator("#dialogBody iframe").locator("#header_title")).to_contain_text("FastQC Report")
    page.set_viewport_size({"width":390, "height":844})
    page.goto(url)
    expect(page.frame_locator("#dock-plots iframe").locator("#header_filename")).to_contain_text("R1")
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    pane = page.locator("#dock-plots")
    pane.scroll_into_view_if_needed()
    pane.screenshot(path=str(EVIDENCE / "窄屏报告.png"))
    page.set_viewport_size({"width":1440, "height":960})
    return {"fastqc_lengths_nt":read_lengths, "reads_per_end":1000000, "multiqc_plots":plots,
            "multiqc_clustered_control":True, "report_image_widths":widths,
            "markdown_internal_links":["样本表.tsv","来源与校验.json"],"narrow_width":390}


def archived_files(page):
    result = {}
    samples = [
        (PROJECT, "*_R1_001.fastq.gz", "pre", "@"),
        (PROJECT, "multiqc.parquet", "table", "anchor"),
        (PROJECT, "*_R1_001_fastqc.zip", "table", "fastqc_data.txt"),
        (PROJECT, "SJ.out.tab", "table", "内含子起点"),
        ("93c74b00c8074bd1", "*.h5ad", "table", "个细胞或细胞核"),
    ]
    for project, pattern, tag, label in samples:
        root = Path(page.request.get(page_url(BASE,"/api/project",project=project)).json()["path"])
        path = next(root.rglob(pattern)).relative_to(root).as_posix()
        page.goto(page_url(BASE,"/panes",project=project,preview=path))
        preview = page.locator("#dock-preview " + tag).last
        expect(preview).to_contain_text(label)
        result[pattern] = {"path":path, "verified":label}
        if pattern.endswith(".parquet"):
            expect(page.locator("#dock-preview .preview-note").first).to_contain_text("22 行，23 列")
            expect(page.locator("#dock-preview details")).to_contain_text("字段与类型")
    return result


@contextmanager
def fixture_service(root):
    class Quiet(Handler):
        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Quiet) as server, report_service(server.server_port) as server.reports:
        server.api = API(root / "registry")
        project = server.api.store.create_project("预览测试", root / "project")
        folder = root / "原始输入"
        folder.mkdir()
        (folder / "assets").mkdir()
        (folder / "assets/view.js").write_text(
            "fetch('assets/data.json').then(r=>r.json()).then(d=>document.getElementById('value').textContent=d.value)", encoding="utf-8")
        (folder / "assets/theme.css").write_text("#value{color:rgb(15,85,45)}", encoding="utf-8")
        (folder / "assets/data.json").write_text('{"value":"39 cells"}', encoding="utf-8")
        (folder / "测试 报告.html").write_text('<meta charset=utf-8><link rel=stylesheet href="assets/theme.css">'
            '<p id=value></p><script src="assets/view.js"></script>', encoding="utf-8")
        Image.new("RGB", (80, 60), "green").save(folder / "质控.pdf", "PDF")
        key = project["id"]
        server.api.post("/api/stage-settings", {"project":key,"settings":{
            "libraries":[{"id":"sample","sample":"A","kind":"matrix","path":str(folder)}],"bindings":{}}})
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", key
        finally:
            server.shutdown()
            thread.join()
            server.api.store.queue.stop()


def fixture_checks(page, base, project):
    args = dict(project=project, previewScope="input", previewLibrary="sample")
    page.goto(page_url(base,"/panes", preview="测试 报告.html", **args))
    report = page.frame_locator("#dock-preview iframe")
    expect(report.locator("#value")).to_have_text("39 cells")
    expect(report.locator("#value")).to_have_css("color", "rgb(15, 85, 45)")
    page.goto(page_url(base,"/panes", preview="质控.pdf", **args))
    reader = page.locator("#dock-preview iframe")
    expect(reader).to_be_visible()
    pdf = page.request.get(reader.get_attribute("src"))
    assert pdf.headers["content-type"] == "application/pdf" and pdf.body().startswith(b"%PDF")
    expect(page.frame_locator("#dock-preview iframe").locator('embed[type="application/pdf"]')).to_be_attached()
    guides = {}
    page.goto(page_url(base,project=project,step=1))
    for step in range(1,6):
        page.locator(f'.step-link[data-step="{step}"]').click()
        guide = page.locator(f'details[data-guide-step="{step}"]')
        guide.locator("summary").click()
        expect(guide.locator("dd")).to_have_count(4)
        expect(guide.locator("dd").last).to_be_visible()
        guides[step] = page.locator(".workflow-guide h2").inner_text()
    page.locator('[data-act="workflow-overview"]').click()
    expect(page.locator(".guide-route [data-act=guide-jump]")).to_have_count(5)
    page.locator("#dialogBody").screenshot(path=str(EVIDENCE / "流程全览.png"))
    page.locator('.guide-route [data-index="2"]').click()
    expect(page.locator("#workHero h1")).to_have_text("质控与清洗")
    modules = {}
    for step, choices in [(3,["features","pca"]),(4,["graph","umap","leiden"])]:
        page.locator(f'.step-link[data-step="{step}"]').click()
        for name in choices:
            page.locator("#singleModule").select_option(name)
            text = page.locator(".module-explanation").inner_text()
            assert text not in modules.values()
            modules[name] = text
    return {"scoped_html_assets":["CSS","JS","JSON"],"pdf_browser_embed":True,"steps":guides,"modules":modules}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as root, fixture_service(Path(root)) as (base, project), sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width":1440,"height":960})
        page.set_default_timeout(12000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        results = {**real_reports(page), "archived_files":archived_files(page), **fixture_checks(page, base, project),
                   "page_errors":errors, "browser":browser.version}
        assert not errors, errors
        browser.close()
    (EVIDENCE/"验证结果.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(results,ensure_ascii=True))


if __name__ == "__main__":
    main()

