"""Local HTTP workbench. Start with the project launcher or python app.py."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qsl, quote, urlsplit
from backend.catalog import DEFAULTS, discover
from backend.inspection import recommendation
from backend.native_reports import report_service
from backend.resources import list_references
from backend.blocks import BLOCKS, recipe
from dataclasses import asdict
from backend.upstream import capabilities
from backend.scheduler import registry_owner
from backend.ports import TASKS, contract, module_definition
from backend import project_views, stage_inputs, stage_files
from backend.workspace import ROOT, Workspace, child, normalize_spec, preview_file

class API:
    def __init__(self,home,max_jobs=2):
        self.store=Workspace(home,max_jobs)
    def get(self,path,q):
        w=self.store
        if path=="/api/health":return {"ok":True,"product":"plant-sc-workbench","version":"0.1"}
        if path=="/api/bootstrap":
            refs=[{**r,"name":r["label"]+" · "+r["assembly"]} for r in list_references()]
            return {"projects":w.projects(),"references":refs,"defaults":DEFAULTS,"tools":capabilities(),
                    "blocks":[{**asdict(b),**module_definition(b.id)} for b in BLOCKS],"tasks":{k:contract(k,True) for k in TASKS},
                    "demo_reference":"ath-tair10-62","demo_project_path":str(ROOT/"workspace"/"花分生组织示例"),
                    "demo_path":str(ROOT/"examples"/"GSM5320262.h5ad"),"home":str(w.home)}
        if path=="/api/project":return w.project(q["project"])
        if path=="/api/projects":return {"projects":w.projects()}
        if path=="/api/queue":return w.queue.status()
        if path=="/api/jobs":return {"jobs":w.jobs(q["project"])}
        if re.fullmatch(r"/api/jobs/[a-z0-9]+",path):return w.job(path.split("/")[-1])
        if path=="/api/stage-files":return stage_files.list_files(w,q["project"],q["job"],int(q["step"]))
        if path=="/api/files":return w.files(q)
        if path=="/api/preview":return preview_file(w.locate(q)[1])
        if path=="/api/plots":return project_views.plots(w,q["project"],q["job"])
        if path=="/api/task-io":return project_views.task_io(w,q["project"],q["job"])
        if path=="/api/run-summary":
            j=w.job(q["job"])
            if j["state"]!="succeeded" or j["project"]!=q["project"]:
                raise ValueError("请选择当前项目已完成的任务。")
            p=w.project(q["project"])
            return json.loads((child(p["path"],j["output"])/"summary.json").read_text(encoding="utf-8"))
        if path=="/api/embedding":
            from backend.plots import embedding_table
            j=w.job(q["job"])
            if j["state"]!="succeeded" or j["project"]!=q["project"]:raise ValueError("请选择本项目已完成的聚类任务。")
            p=w.project(q["project"]);return embedding_table(child(p["path"],j["output"])/"cells.tsv")
        raise KeyError("接口不存在。")
    def post(self,path,b):
        if path=="/api/stage-source":
            self.store.project(b["project"])
            return stage_inputs.describe(b["path"],b["role"],b.get("module"),b.get("params"))
        if path=="/api/stage-settings":
            pid=self.store.project(b["project"])["id"]
            settings=b["settings"]
            if not isinstance(settings,dict) or not isinstance(settings.get("libraries"),list) or not isinstance(settings.get("bindings"),dict):
                raise ValueError("工作位输入清单无效")
            with self.store.connect() as db:
                db.execute("INSERT OR REPLACE INTO stage_settings VALUES (?,?)",(pid,json.dumps(settings,ensure_ascii=False)))
            return {"saved":True}
        if path=="/api/projects":return self.store.create_project(b["name"],b.get("path"))
        if path=="/api/files/mkdir":return project_views.make_dir(self.store,b)
        if path=="/api/files/copy":return project_views.copy_file(self.store,b)
        if path=="/api/files/reveal":return project_views.reveal(self.store,b)
        if path=="/api/project-inputs":
            proj=self.store.project(b["project"]);normalize_spec(b)
            with self.store.connect() as db:
                db.execute("UPDATE projects SET last_spec=? WHERE id=?",(json.dumps(b,ensure_ascii=False),proj["id"]))
            return self.store.project(proj["id"])
        if path=="/api/discover":
            libs=discover(b["path"])
            for lib in libs:
                if Path(lib["path"]).resolve()==(ROOT/"examples"/"GSM5320262.h5ad").resolve():
                    lib.update(modality="snRNA",species="Arabidopsis thaliana",organ="花分生组织")
            try:ref=recommendation(libs)
            except (KeyError,ValueError,OSError,TypeError):ref=None
            return {"libraries":libs,"recommendation":ref,"recommended_reference":ref["id"] if ref else None}
        if path=="/api/qc-preview":
            from backend.analysis import preview_qc
            spec=normalize_spec(b)
            for lib in spec["libraries"]:
                if lib.get("kind")=="raw" and lib.get("filtered_path"):
                    lib.update(path=lib["filtered_path"],kind="matrix")
            return preview_qc(spec)
        if path=="/api/recipe":
            spec=self.store.prepare(b)[1] if b.get("project") else normalize_spec(b)
            return recipe(spec,capabilities())
        if path=="/api/jobs":return self.store.submit(b)
        if re.fullmatch(r"/api/jobs/[a-z0-9]+/cancel",path):
            return self.store.cancel(path.split("/")[3])
        if path=="/api/pick":
            if b.get("kind") not in ("file","directory"):raise ValueError("未知选择器类型。")
            # Tk dialogs live in an independent main thread of a short-lived helper.
            p=subprocess.run([sys.executable,str(ROOT/"backend"/"picker.py"),b["kind"]],capture_output=True,timeout=180)
            if p.returncode:raise ValueError("系统文件选择器不可用，请粘贴本地完整路径。")
            return {"path":p.stdout.decode("utf-8").strip()}
        raise KeyError("接口不存在。")
class Handler(BaseHTTPRequestHandler):
    def json(self,code,obj):
        b=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode("utf-8")
        self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def serve_file(self,p,data=False,download=False):
        if not p.is_file():raise FileNotFoundError("找不到文件。")
        self.send_response(200)
        mime=mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        if p.suffix==".js":mime="text/javascript"
        self.send_header("Content-Type",mime+("; charset=utf-8" if mime.startswith("text/") else ""))
        if data:
            self.send_header("Content-Security-Policy","sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'")
            self.send_header("Content-Disposition",("attachment" if download else "inline")+"; filename*=UTF-8''"+quote(p.name))
        self.send_header("X-Content-Type-Options","nosniff");self.send_header("Content-Length",str(p.stat().st_size));self.end_headers()
        with p.open("rb") as f:shutil.copyfileobj(f,self.wfile,128*1024)
    def dispatch(self,post):
        try:
            host=self.headers.get("Host","").split(":")[0].lower()
            if host not in ("localhost","127.0.0.1"):return self.json(403,{"error":"仅限本机工作台访问。"})
            parsed=urlsplit(self.path);path=parsed.path;q=dict(parse_qsl(parsed.query,keep_blank_values=True))
            if post:
                origin=self.headers.get("Origin")
                if origin and urlsplit(origin).netloc.lower()!=self.headers.get("Host","").lower():return self.json(403,{"error":"页面来源不匹配。"})
                length=int(self.headers.get("Content-Length","0"))
                if path=="/api/stage-upload":
                    if self.headers.get_content_type()!="application/octet-stream":raise ValueError("请选择二进制文件批次")
                    return self.json(200,stage_inputs.receive(self.server.api.store,q,self.rfile,length))
                if not 0<length<=1500000 or self.headers.get_content_type()!="application/json":return self.json(400,{"error":"需要 JSON 请求。"})
                return self.json(200,self.server.api.post(path,json.loads(self.rfile.read(length))))
            if path=="/api/native-preview":return self.json(200,self.server.reports.document(self.server.api.store.locate(q)[1]))
            if path=="/api/file":return self.serve_file(self.server.api.store.locate(q)[1],True,q.get("download")=="1")
            if path.startswith("/api/"):return self.json(200,self.server.api.get(path,q))
            if path in ("/files","/plots","/jobs","/panes"):return self.serve_file(ROOT/"web"/"index.html")
            return self.serve_file(child(ROOT/"web",path.lstrip("/") or "index.html"))
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except FileNotFoundError as e:self.json(404,{"error":str(e)})
        except (ValueError,KeyError,TypeError,PermissionError,OSError) as e:self.json(400,{"error":str(e)})
        except Exception as e:
            import traceback
            traceback.print_exc();self.json(500,{"error":str(e)})
    def do_GET(self):self.dispatch(False)
    def do_POST(self):self.dispatch(True)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port",type=int,default=8876)
    p.add_argument("--home",default=str(ROOT/"workspace"))
    p.add_argument("--max-jobs",type=int,default=2)
    args=p.parse_args()
    with registry_owner(args.home), ThreadingHTTPServer(("127.0.0.1",args.port),Handler) as server:
        server.api=API(args.home,args.max_jobs)
        print(f"植物单细胞工作台 http://127.0.0.1:{server.server_port}",flush=True)
        with report_service(server.server_port) as server.reports:
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:
                for jid in server.api.store.queue.stop():server.api.store.cancel(jid)
if __name__=="__main__":main()

