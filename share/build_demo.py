"""Rebuild the curated GEO demonstration from the original two local example runs."""
import base64
import gzip
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.file_preview import preview_file
from backend.native_reports import FASTQC_STYLE
from share.serve import DEMO, route_key

LOCAL = "http://127.0.0.1:8876"
SAMPLES = [
    ("d02e9770456b451d", "3798825899a84d19", "拟南芥花分生组织 · 测序质检"),
    ("dceb6557e15b4b87", "073c9a6d94dd4def", "拟南芥花分生组织 · 质控与聚类"),
]


def source(route, **params):
    with urlopen(LOCAL + "/api/" + route + "?" + urlencode(params), timeout=30) as response:
        return json.load(response)


def portable(value):
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [portable(v) for v in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        if re.match(r"^(?:[A-Za-z]:/|/(?:mnt|home|Users|tmp)/|//)", normalized):
            if "/runs/" in normalized:
                return "runs/" + normalized.split("/runs/")[-1]
            return normalized.rsplit("/", 1)[-1]
    return value


def clean_report(path):
    data = path.read_bytes()
    if path.name.endswith("_fastqc.html"):
        try:
            text = data.decode("utf8")
        except UnicodeError:
            text = data.decode("gb18030")
        return text.replace("</head>", FASTQC_STYLE.decode() + "</head>").encode()
    text = data.decode("utf8")
    if path.name == "multiqc_report.html":
        text = re.sub(r'(<code class="mqc_analysis_path">).*?(</code>)', r'\1read_qc\2', text, flags=re.S)
        def plot_data(match):
            raw = json.loads(gzip.decompress(base64.b64decode(match[2])))
            packed = gzip.compress(json.dumps(portable(raw), ensure_ascii=False).encode(), mtime=0)
            return match[1] + base64.b64encode(packed).decode() + match[3]
        text = re.sub(r'(<script[^>]*id="mqc_compressed_plotdata"[^>]*>)([^<]+)(</script>)', plot_data, text)
    return text.encode()


def main():
    routes, files, projects = {}, [], []
    def add(name, value, **params):
        routes[route_key("/api/"+name, params)] = value

    for number, (pid, jid, title) in enumerate(SAMPLES):
        project = source("project", project=pid)
        root = Path(project["path"])
        job = next(j for j in source("jobs", project=pid)["jobs"] if j["id"] == jid)
        out = job["output"]
        results = root / out
        exported = DEMO / "files" / pid
        exported.mkdir(parents=True, exist_ok=True)
        inventory = {}
        def publish(rel, data):
            dest = exported / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            files.append(pid + "/" + rel)
            inventory[rel] = len(data)
            if dest.suffix.lower() in {".md", ".tsv", ".txt", ".json"}:
                add("preview", preview_file(dest), project=pid, path=rel)
        if number == 0:
            reports = sorted((results/"capture-001/read_qc").glob("*.html"))
            note = "分别打开 R1、R2 的 FastQC，在 Basic Statistics 中查看读长。打开 MultiQC 可对照两端的质量分布。"
        else:
            reports = [results/"report.html"]
            note = "从逐捕获质控图查看保留情况，再切换交互 UMAP 对照簇与样本。打开完整报告可连贯阅读全部图表。"
            for filename in ("cells.tsv", "qc_cells.tsv", "qc_libraries.tsv", "cluster_samples.tsv",
                             "pca_variance.tsv", "cluster_comparison.tsv", "cluster_membership_overlap.tsv",
                             "qc.png", "pca.png", "embedding.png", "cluster_comparison.png"):
                publish(out + "/" + filename, (results/filename).read_bytes())
        for report in reports:
            publish(report.relative_to(root).as_posix(), clean_report(report))
        links = "\n".join("- [" + p.name + "](" + p.relative_to(root).as_posix() + ")" for p in reports)
        if number:
            links += "\n- [逐捕获质控表](" + out + "/qc_libraries.tsv)"
        publish("操作卡.md", (f"# {title}\n\n{note}\n\n{links}\n\n数据来自 "
                "[GEO GSM5320262](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM5320262)。"
                + ("测序练习取前一百万对读段。" if not number else "矩阵练习使用公开样本的 1,200 个核。")
                + "\n\n可通过右上角的项目选择器切换两个示例。").encode())
        project_info = {"id":pid, "name":title, "path":title, "created":project["created"],
                        "last_spec":{"reference":"ath-tair10-62", "libraries":[], "params":{}},
                        "stage_inputs":{"libraries":[], "bindings":{}}}
        projects.append(project_info)
        params = {"project":pid, "job":jid}
        add("project", project_info, project=pid)
        add("jobs", {"jobs":[portable(job)]}, project=pid)
        io = portable(source("task-io", **params))
        io["project_path"] = title
        publish(out+"/task-io.json", json.dumps(io, ensure_ascii=False, indent=2).encode())
        add("task-io", io, **params)
        items = source("plots", **params)
        items["items"] = [x for x in items["items"] if x["source"] in inventory]
        for item in items["items"]:
            if item.get("vector") not in inventory:
                item.pop("vector", None)
        add("plots", items, **params)
        if number:
            for name in ("embedding","run-summary"):
                add(name, portable(source(name, **params)), **params)
        for step in range(1,6):
            stage = source("stage-files", step=step, **params)
            stage["items"] = [x for x in stage["items"] if x["path"] in inventory]
            add("stage-files", stage, step=str(step), **params)
        tree = {"":{}}
        for path, size in inventory.items():
            parts = path.split("/")
            for i, name in enumerate(parts):
                parent = "/".join(parts[:i])
                rel = "/".join(parts[:i+1])
                is_file = i == len(parts)-1
                tree.setdefault(parent, {})[name] = {"name":name, "path":rel, "type":"file" if is_file else "dir",
                                                     "size":size if is_file else 0, "mtime":None}
        for path, entries in tree.items():
            add("files", {"entries":list(entries.values()),"absolute":"/"+title+"/"+path,"path":path}, project=pid, path=path)

    bootstrap = source("bootstrap")
    bootstrap.update(projects=projects, read_only=True, demo_project_path=projects[0]["path"], home="", demo_path="")
    bootstrap["tools"] = {k:{"available":False,"detail":"共享演示仅供浏览"} for k in bootstrap["tools"]}
    add("bootstrap", portable(bootstrap))
    add("queue", {"limit":0,"active":0,"waiting":0})
    add("projects", {"projects":projects})
    add("health", {"ok":True,"product":"plant-sc-workbench-share","read_only":True})
    first, job, _ = SAMPLES[0]
    figure = next(rel.split("/"+job+"/")[1] for rel in files if "_R1_" in rel and rel.endswith(".html"))
    start = "/?" + urlencode({"project":first,"job":job,"step":2,"left":"preview","preview":"操作卡.md","figure":figure})
    catalog = {"start":start,"routes":routes,"files":sorted(files)}
    (DEMO / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print(len(routes), "read-only routes;", len(files), "artifacts")


if __name__ == "__main__":
    main()

