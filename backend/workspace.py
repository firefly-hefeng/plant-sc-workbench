"""Project registry, foreground inspection and supervised compute jobs."""
from .file_preview import preview_file
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
from functools import lru_cache
from datetime import datetime, timezone
from contextlib import closing,contextmanager
from uuid import uuid4
from .catalog import DEFAULTS, absolute
from .scheduler import JobQueue
from .ports import SINGLE_MODULES, TASKS

ROOT=Path(__file__).resolve().parents[1]
def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def write_json(p,obj):
    p=Path(p);tmp=p.with_name(p.name+"."+uuid4().hex+".tmp")
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        os.replace(tmp,p)
    finally:
        tmp.unlink(missing_ok=True)
def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))
@lru_cache(maxsize=1024)
def analysis_uses_reads(request_path):
    try:return any(lib.get("kind")=="fastq" for lib in read_json(request_path).get("libraries",[]))
    except (OSError,ValueError):return False

def child(root,rel):
    root=Path(root).resolve()
    target=(root/str(rel)).resolve()
    if not target.is_relative_to(root):raise ValueError("路径超出当前选择的目录。")
    return target
def normalize_spec(payload):
    from .resources import resolve_reference
    action=payload.get("action","analysis")
    if action not in TASKS:raise ValueError("未知的工作台动作。")
    if payload.get("external_h5ad") and action not in SINGLE_MODULES:
        raise ValueError("外部交接对象适用于特征、PCA、邻居图、UMAP 或 Leiden 单模块任务")
    params=DEFAULTS|payload.get("params",{})
    if params["quantifier"] not in ("cellranger","starsolo"):raise ValueError("请选择受支持的定量引擎。")
    if params.get("analysis_layer","counts")=="soupx" and action=="analysis" and params["ambient_mode"]!="soupx" and not all(
            r.get("corrected_path") for r in payload.get("libraries",[])):
        raise ValueError("选择 SoupX 分析层前，请启用污染校正或提供已校正的配套矩阵。")
    if params.get("cell_calling") not in ("upstream","emptydrops") or params.get("ambient_mode") not in ("off","soupx"):
        raise ValueError("条码调用或环境 RNA 策略不可识别。")
    libs=payload.get("libraries",[])
    if not isinstance(libs,list) or len(libs)>256:raise ValueError("请核对文库列表。")
    if not libs and action not in ("build_reference","recluster","from_qc",*SINGLE_MODULES):raise ValueError("请先选择或发现至少一个文库。")
    names=set();records=[];sources=set()
    for lib in libs:
        r=dict(lib);r["path"]=str(absolute(r["path"])); lid=str(r["id"]).strip()
        if not lid or lid in names or any(c in lid for c in '\x00/\\'):raise ValueError("文库 ID 需要唯一且不含路径分隔符。")
        names.add(lid);r["id"]=lid;r["sample"]=r.get("sample") or lid
        if r.get("kind","matrix") not in ("raw","matrix","filtered","h5ad","fastq","mex","h5"):raise ValueError("无法识别输入的文库类型。")
        identity=(Path(r["path"]).resolve(),r.get("prefix","") if r.get("kind")=="fastq" else None)
        for k in ("filtered_path","raw_path","corrected_path","clusters_tsv"):
            if r.get(k):r[k]=str(absolute(r[k]))
        inputs={identity}|{(Path(r[k]).resolve(),None) for k in ("filtered_path","raw_path") if r.get(k)}
        if inputs & sources:raise ValueError("同一物理捕获输入被重复登记")
        sources.update(inputs)
        records.append(r)
    rid=payload.get("reference") or "none"
    if isinstance(rid,dict):rid=rid.get("id","none")
    if rid=="custom" and not payload.get("custom_reference"):raise ValueError("请选择自定义基因集文件。")
    if rid=="none":
        ref={"id":"none","name":"未指定参考","sets":{"mitochondria":[],"plastid":[]}}
    else:ref=resolve_reference(rid,payload.get("custom_reference"))
    if "sets" not in ref:
        ref["sets"]={"mitochondria":ref.get("mitochondrial",ref.get("mitochondria",[])),"plastid":ref.get("plastid",[])}
    return {"action":action,"libraries":records,"params":params,"reference":ref,"parent_job":payload.get("parent_job"),
            "external_h5ad":payload.get("external_h5ad"),"custom_reference":payload.get("custom_reference"),"modality":payload.get("modality","scRNA")}
class Workspace:
    def __init__(self,home,max_jobs=2):
        self.home=Path(home).resolve(); self.home.mkdir(parents=True,exist_ok=True)
        self.db=self.home/"registry.sqlite";self.lock=threading.RLock();self.processes={}
        self.queue=JobQueue(max_jobs,self.execute)
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS stage_settings(project TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,path TEXT UNIQUE,created TEXT,last_spec TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project TEXT,state TEXT,message TEXT,created TEXT,ended TEXT,action TEXT,output TEXT);""")
            db.execute("UPDATE jobs SET state='interrupted',message='服务重新启动，可从保存的参数重新运行。',ended=? WHERE state IN ('running','queued')",(timestamp(),))
    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.db,timeout=20)) as conn:
            conn.row_factory=sqlite3.Row
            with conn:
                yield conn
    def projects(self):
        with self.connect() as db:return [dict(r) for r in db.execute("SELECT id,name,path,created FROM projects ORDER BY created DESC,rowid DESC")]
    def project(self,pid):
        with self.connect() as db:r=db.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
        if not r:raise KeyError("项目不存在。")
        d=dict(r);d["last_spec"]=json.loads(d["last_spec"]) if d["last_spec"] else None
        with self.connect() as db:settings=db.execute("SELECT data FROM stage_settings WHERE project=?",(pid,)).fetchone()
        d["stage_inputs"]=json.loads(settings[0]) if settings else {}
        return d
    def create_project(self,name,path=""):
        name=str(name or "").strip()
        if not name or len(name)>120:raise ValueError("请填写项目名称（最多 120 字）。")
        pid=uuid4().hex[:16]
        root=Path(path).expanduser().resolve() if path else self.home/"projects"/pid
        root.mkdir(parents=True,exist_ok=True)
        if not root.is_dir() or root==Path(root.anchor):raise ValueError("请选择一个具体项目目录。")
        with self.connect() as db:
            row=db.execute("SELECT id FROM projects WHERE path=?",(str(root),)).fetchone()
            if row:return self.project(row[0])
            db.execute("INSERT INTO projects VALUES(?,?,?,?,NULL)",(pid,name,str(root),timestamp()))
        return self.project(pid)
    def prepare(self,payload):
        proj=self.project(payload["project"])
        spec=normalize_spec(payload)
        if spec["action"] in SINGLE_MODULES:
            from .component_jobs import resolve_source
            resolve_source(self,proj,spec)
        if spec["action"]=="recluster":
            prev=self.job(spec.get("parent_job"))
            if prev["project"]!=proj["id"] or prev["state"]!="succeeded":raise ValueError("请选择当前项目中成功生成邻居图的任务。")
            obj=child(proj["path"],prev["output"])/"analysis.h5ad"
            if not obj.is_file():raise ValueError("该任务没有可复用的 analysis.h5ad。")
            spec["graph_h5ad"]=str(obj)
            parent_params=obj.parent/"parameters.json"
            if parent_params.is_file():
                original=read_json(parent_params)
                if original.get("reference"):
                    spec["reference"]=original["reference"]
        if spec["action"]=="from_qc":
            prev=self.job(spec.get("parent_job"))
            if prev["project"]!=proj["id"] or prev["state"]!="succeeded" or prev["action"]!="quality":
                raise ValueError("请选择当前项目中成功完成的质控任务。")
            output=child(proj["path"],prev["output"])
            spec["libraries"]=[]
            spec["checkpoint_h5ad"]=str(output/"qc.h5ad")
            spec["reference"]=read_json(output/"parameters.json")["reference"]
        return proj,spec

    def submit(self,payload):
        proj,spec=self.prepare(payload)
        jid=uuid4().hex[:16]
        base=child(proj["path"],"runs/"+jid);base.mkdir(parents=True)
        write_json(base/"request.json",spec);write_json(base/"form.json",payload)
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",(jid,proj["id"],"queued","等待计算",timestamp(),None,spec["action"],f"runs/{jid}/results"))
            if spec["action"]=="analysis":db.execute("UPDATE projects SET last_spec=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),proj["id"]))
        self.queue.submit(jid,base)
        return self.job(jid)
    def execute(self,jid,base):
        try:
            with self.lock:
                with self.connect() as db:
                    if not db.execute("UPDATE jobs SET state='running',message='正在加载计算工具' WHERE id=? AND state='queued'",(jid,)).rowcount:return
                env=os.environ.copy()
                env.update(PYTHONIOENCODING="utf-8",PYTHONUTF8="1",MPLBACKEND="Agg")
                for key in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","NUMBA_NUM_THREADS","MKL_NUM_THREADS"):env[key]="2"
                with (base/"run.log").open("wb") as log:
                    proc=subprocess.Popen([sys.executable,"-m","backend.worker",str(base)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env,
                                          start_new_session=os.name!="nt",creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                self.processes[jid]=proc
            code=proc.wait()
            success=code==0 and (base/"results"/"receipt.json").exists()
            msg="运行完成" if success else "运行失败，可检查 run.log 后重试。"
            if not success and (base/"error.json").is_file():msg=read_json(base/"error.json").get("message",msg)
        except Exception as e:
            success=False;msg=str(e)
        finally:
            with self.lock:self.processes.pop(jid,None)
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?,message=?,ended=? WHERE id=? AND state='running'",("succeeded" if success else "failed",msg,timestamp(),jid))
    def job(self,jid):
        with self.connect() as db:
            r=db.execute("SELECT jobs.*,projects.path AS project_path FROM jobs JOIN projects ON projects.id=jobs.project WHERE jobs.id=?",(jid,)).fetchone()
        if not r:raise KeyError("任务不存在。")
        d=dict(r);path=Path(d.pop("project_path"))/"runs"/d["id"]/"progress.json"
        if d["action"]=="analysis":d["has_reads"]=analysis_uses_reads(path.with_name("request.json"))
        d["progress"]=100 if d["state"]=="succeeded" else 0
        if d["state"]=="succeeded" and d["action"] in (*SINGLE_MODULES,"quality","analysis","from_qc","recluster"):
            from .component_jobs import supported_modules
            filename="component.h5ad" if d["action"] in SINGLE_MODULES else "qc.h5ad" if d["action"]=="quality" else "analysis.h5ad"
            source=path.parent/"results"/filename
            d["available_modules"]=supported_modules(source,source.stat().st_mtime_ns) if source.is_file() else []
        if path.is_file() and d["state"]=="running":
            try:d.update(read_json(path))
            except (OSError,ValueError):pass
        return d
    def jobs(self,pid):
        self.project(pid)
        with self.connect() as db:ids=[r[0] for r in db.execute("SELECT id FROM jobs WHERE project=? ORDER BY rowid DESC",(pid,))]
        return [self.job(x) for x in ids]
    def cancel(self,jid):
        with self.lock:
            job=self.job(jid)
            if job["state"] not in ("running","queued"):return job
            self.queue.remove(jid)
            p=self.processes.get(jid)
            if p and p.poll() is None:
                if os.name=="nt":subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                else:os.killpg(p.pid,signal.SIGTERM)
            with self.connect() as db:db.execute("UPDATE jobs SET state='cancelled',message='用户取消',ended=? WHERE id=?",(timestamp(),jid))
        return self.job(jid)
    def locate(self,q):
        p=self.project(q["project"]);root=Path(p["path"])
        if q.get("scope")=="input":
            saved=p["last_spec"] or {}; libs=p["stage_inputs"].get("libraries",[])+saved.get("libraries",[])
            lib=next((x for x in libs if x["id"]==q.get("library")),None)
            if lib:
                path=absolute(lib["path"])
            else:
                keys=str(q.get("library","")).split("/")
                if len(keys)!=4 or keys[:2]!=["","object"]:raise ValueError("请选择项目中已登记的输入")
                obj=p["stage_inputs"].get("bindings",{}).get(keys[2],{}).get("objects",{}).get(keys[3],{})
                path=absolute(obj.get("file"))
            root=path if path.is_dir() else path.parent
        return root,child(root,q.get("path","") or ".")
    def files(self,q):
        root,p=self.locate(q)
        entries=[]
        for x in sorted(p.iterdir(),key=lambda f:(not f.is_dir(),f.name.casefold())):
            if x.name.startswith(".") or not x.resolve().is_relative_to(root):continue
            try:s=x.stat()
            except OSError:continue
            entries.append({"name":x.name,"path":x.relative_to(root).as_posix(),"type":"dir" if x.is_dir() else "file",
                            "size":s.st_size if x.is_file() else 0,"mtime":datetime.fromtimestamp(s.st_mtime,timezone.utc).isoformat()})
        return {"path":p.relative_to(root).as_posix(),"absolute":str(p),"entries":entries}



