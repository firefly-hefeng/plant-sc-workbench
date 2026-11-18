"""MCP stdio adapter for the local scientific service (newline-delimited JSON-RPC)."""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
TYPES={"project":{"type":"string"},"path":{"type":"string"},"name":{"type":"string"},"job":{"type":"string"},
       "libraries":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"path":{"type":"string"},"kind":{"enum":["matrix","raw","fastq","filtered","h5ad","mex","h5"]},"sample":{"type":"string"},"modality":{"enum":["scRNA","snRNA"]}},"required":["id","path"]}},
       "reference":{"type":"string","description":"Use an ID from catalog, custom or none."},"custom_reference":{"type":"string"},
       "params":{"type":"object","description":"分析参数覆盖值；省略以采用 catalog 中的默认值。"},
       "action":{"type":"string"},"parent_job":{"type":"string"}}
# These schemas are returned during MCP discovery so the agent can build valid no-code recipes.
sys.path.insert(0,str(ROOT))
from backend.catalog import DEFAULTS
from backend.ports import TASKS
TYPES["action"]["enum"]=list(TASKS)
TYPES["modality"]={"enum":["scRNA","snRNA"],"description":"默认为 scRNA，文库级设置优先。"}
settings={}
for key,value in DEFAULTS.items():
    if value is None:kind=["number","null"]
    elif isinstance(value,bool):kind="boolean"
    elif isinstance(value,int):kind="integer"
    elif isinstance(value,float):kind="number"
    elif isinstance(value,list):kind="array"
    else:kind="string"
    settings[key]={"type":kind,"default":value}
settings["graph_representation"]={"type":"string","enum":["auto","X_pca","X_pca_harmony"],"default":"auto"}
for key,choices in {
    "quantifier":["starsolo","cellranger"],"chemistry":["auto","SC3Pv3","SC3Pv3_10"],
    "cell_calling":["upstream","emptydrops"],"doublet_mode":["report","remove","off"],
    "ambient_mode":["off","soupx"],"analysis_layer":["counts","soupx"],"hvg_method":["seurat","seurat_v3"],
    "integration":["none","harmony"],"feature_join":["strict","intersection"]}.items():
    settings[key]["enum"]=choices
for key,lower,upper in (("hvg",3,100000),("n_pcs",2,500),("n_neighbors",2,1000),("threads",1,512),
                        ("max_mito_pct",0,100),("max_plastid_pct",0,100),("expected_doublet_rate",.00001,.49999),
                        ("min_counts",0,2**31-1),("min_genes",0,2**31-1),("mad_multiplier",0,100),
                        ("seed",0,2**31-1),("memory_gb",1,4096),("lower",1,1000000),("min_dist",0,1)):
    settings[key].update(minimum=lower,maximum=upper)
settings["resolutions"].update(items={"type":"number","exclusiveMinimum":0,"maximum":100},minItems=1,maxItems=16)
for key in ("star_index","whitelist","reference_dir","fasta","gtf","clusters_tsv","ref_name"):
    settings[key]={"type":"string"}
settings["batch_hvg"]={"type":"boolean"}
settings["min_cells_per_gene"]={"type":"integer","minimum":1}
TYPES["params"].update(properties=settings,additionalProperties=False)
library=TYPES["libraries"]["items"]["properties"]
for key in ("condition","batch","species","organ","counts_layer","prefix","filtered_path","raw_path","clusters_tsv","corrected_path","corrected_counts_layer"):
    library[key]={"type":"string"}
library["params"]={"type":"object","properties":{k:settings[k] for k in ("min_counts","min_genes","mad_multiplier","max_mito_pct","max_plastid_pct","doublet_mode","expected_doublet_rate")},"additionalProperties":False}
TYPES["parent_job"]["description"]="from_qc 需要本项目已成功的 quality 任务；recluster 需要本项目已成功的含邻居图任务。features、pca、graph、umap、leiden 分别从已成功父任务读取所需字段，可串接或分支。"
TYPES["libraries"]["description"]="每个物理捕获一项。优先使用 discover 返回的完整记录；FASTQ 需 prefix，raw 可指定同一捕获的 filtered_path。"
TYPES["module"]={"type":"string","description":"可选，只读取一个计算模块，如 qc、graph 或 leiden。"}
TYPES["capture"]={"type":"string","description":"可选，按物理捕获 ID 筛选模块。"}
TYPES["include_inventory"]={"type":"boolean","default":False,"description":"包含逐文件列表和指纹，大任务优先使用清单路径。"}
TYPES["external_h5ad"]={"type":"string","description":"单模块可直接选取本地 H5AD，与 parent_job 二选一。按动作检查必需字段、记录来源指纹。"}
SPEC=["project","external_h5ad","libraries","reference","custom_reference","modality","params","action","parent_job"]
TYPES.update(species={"type":"string"},organ={"type":"string"},output_folder={"type":"string"},
             annotation_method={"enum":["specificity","prevalence"]},capture_key={"type":"string","default":"capture"},
             counts_layer={"type":"string"},batch_from_capture={"type":"boolean","default":False})
DEFS={
"split_captures":("按用户指定的物理捕获字段拆分整数 H5AD，返回可直接传给 run 的 libraries 清单。",
                 ["external_h5ad","output_folder","capture_key","counts_layer","modality","batch_from_capture"],["external_h5ad","output_folder"]),
"annotate_clusters":("使用同物种、器官、模态和组装的文献面板。输入含 counts 和 leiden 的本地 H5AD，输出条码身份、逐簇依据与运行回执。",
                     ["external_h5ad","output_folder","species","organ","modality","reference","annotation_method"],
                     ["external_h5ad","output_folder","species","organ","modality","reference"]),
"catalog":("查看工作台内置模块、默认参数、已安装工具和当前项目。",[],[]),
"new_project":("在本地建立工作目录，返回项目 ID。",["name","path"],["name"]),
"discover":("发现本地 FASTQ、MEX、H5 或 H5AD 并匹配参考。",["path"],["path"]),
"plan":("按输入检查流程配方，查看模块顺序、参数和缺项。",SPEC,["project"]),
"preview_qc":("预览分捕获过滤影响，返回生物学诊断摘要。",SPEC,["project","libraries"]),
"run":("执行已选配方。返回可查询的异步任务 ID；从质控继续 from_qc 和重分群 recluster 需提供 parent_job。",SPEC,["project"]),
"status":("检查任务状态和结果目录。",["job"],["job"]),
"task_io":("读取任务接口及实际端口。可按模块和捕获查询，并获取完整清单路径。",["project","job","module","capture","include_inventory"],["project","job"]),
"list_results":("查看工作项目中的目录及产物。",["project","path"],["project"]),
"read_table":("查看项目内的结果表或文本摘要。",["project","path"],["project","path"])}
def schemas():
    return [{"name":k,"description":d,"inputSchema":{"type":"object","properties":{f:TYPES[f] for f in fields},"required":req,"additionalProperties":False}} for k,(d,fields,req) in DEFS.items()]
def api(method,path,data=None):
    b=json.dumps(data,ensure_ascii=False).encode() if data is not None else None
    req=Request(BASE+path,data=b,method=method,headers={"Content-Type":"application/json"})
    try:
        with urlopen(req,timeout=150) as res:return json.load(res)
    except HTTPError as e:
        raise ValueError(json.load(e).get("error",str(e))) from e
def call(name,a):
    if name not in DEFS:raise ValueError("未知工具")
    if name=="split_captures":
        from backend.capture_inputs import split_file
        return {"libraries":split_file(a["external_h5ad"],a["output_folder"],a.get("capture_key","capture"),
                                       a.get("counts_layer"),a.get("modality"),a.get("batch_from_capture",False))}
    if name=="annotate_clusters":
        from backend.annotation import run_annotation
        return run_annotation(a["external_h5ad"],a["output_folder"],a["species"],a["organ"],a["modality"],
                              a["reference"],a.get("annotation_method","specificity"))
    if name=="catalog":
        d=api("GET","/bootstrap")
        d["references"]=[{k:r.get(k) for k in ("id","name","assembly","counts")} for r in d["references"]]
        return d
    if name=="status":return api("GET","/jobs/"+str(a["job"]))
    if name=="task_io":
        data=api("GET","/task-io?"+urlencode({k:a[k] for k in ("project","job")}))
        data["modules"]=[m for m in data["modules"] if all(not a.get(k) or m.get(k)==a[k] for k in ("module","capture"))]
        if not a.get("include_inventory"):
            for row in [data,*data["modules"]]:
                for field in ("inputs","outputs"):
                    if "products" in row[field]:
                        row[field]["product_count"]=len(row[field].pop("products"))
            data["input_file_count"]=len(data.pop("input_files",[]))
            if "partial_outputs" in data:
                data["partial_file_count"]=len(data.pop("partial_outputs"))
        if data["schema"]=="plant-task-io/1":
            data["manifest_path"]="runs/"+a["job"]+"/results/task-io.json"
        return data
    if name in ("list_results","read_table"):
        d=api("GET",("/files?" if name=="list_results" else "/preview?")+urlencode(a))
        if "text" in d and len(d["text"])>18000:d.update(text=d["text"][:18000],truncated=True)
        return d
    route={"new_project":"/projects","discover":"/discover","preview_qc":"/qc-preview","run":"/jobs","plan":"/recipe"}[name]
    if name=="run":
        p=api("POST","/recipe",a)
        if not p["ready"]:raise ValueError("；".join(s for x in p["blocks"] for s in x["issues"]))
    d=api("POST",route,a)
    if name=="preview_qc":
        for lib in d["libraries"]:lib.pop("preview_points",None)
    return d
def main():
    for line in sys.stdin.buffer:
        msg = {}
        try:
            msg=json.loads(line)
            if "id" not in msg:continue
            m=msg.get("method");a=msg.get("params",{})
            if m=="initialize":
                supported=["2025-11-25","2025-06-18","2025-03-26","2024-11-05"]
                requested=a.get("protocolVersion")
                result={"protocolVersion":requested if requested in supported else supported[0],"capabilities":{"tools":{}},"serverInfo":{"name":"plant-workbench","version":"0.1.0"}}
            elif m=="tools/list":result={"tools":schemas()}
            elif m=="tools/call":
                try:result={"content":[{"type":"text","text":json.dumps(call(a["name"],a.get("arguments",{})),ensure_ascii=False)}]}
                except Exception as e:result={"isError":True,"content":[{"type":"text","text":str(e)}]}
            elif m=="ping":result={}
            else:raise ValueError("Unsupported method: "+str(m))
            reply={"jsonrpc":"2.0","id":msg["id"],"result":result}
        except json.JSONDecodeError as e:
            reply={"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":str(e)}}
        except Exception as e:
            reply={"jsonrpc":"2.0","id":msg.get("id") if isinstance(msg,dict) else None,"error":{"code":-32601,"message":str(e)}}
        sys.stdout.buffer.write(json.dumps(reply,ensure_ascii=False).encode()+b"\n");sys.stdout.buffer.flush()
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--port",type=int,default=8876);p.add_argument("--print-config",action="store_true");a=p.parse_args()
    BASE=f"http://127.0.0.1:{a.port}/api"
    if a.print_config:
        print(json.dumps([{"id":"mcp-plant-workbench","name":"@deepseek-ai/dsh-mcp-client","config":{"serverName":"plantsc","transport":"stdio","command":sys.executable,"args":[str(Path(__file__).resolve()),"--port",str(a.port)]}}],ensure_ascii=False,indent=2))
    else:main()

