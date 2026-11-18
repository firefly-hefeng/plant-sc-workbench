"""Versioned scientific interfaces and their concrete bindings in a finished job."""
from pathlib import Path
import json

# Each key names a data product across producers and consumers.
TYPES = {
    "reads": ("FASTQ[]", "成对测序文件"), "index": ("directory", "定量索引"),
    "fasta": ("FASTA", "基因组序列"), "gtf": ("GTF", "配套基因注释"),
    "whitelist": ("text", "细胞条码白名单"), "report": ("HTML[]", "测序质检报告"),
    "raw": ("UMI droplets", "未过滤液滴计数"), "counts": ("UMI counts", "候选细胞原始计数"),
    "calls": ("TSV", "条码判定与 FDR"), "groups": ("TSV", "粗分群"),
    "corrected": ("matrix", "背景校正层"), "rho": ("number", "估计污染率"),
    "reference": ("JSON", "稳定基因 ID 参考"), "metrics": ("TSV[]", "按捕获的筛选指标与决定"),
    "merged": ("matrix", "保留细胞的对齐原始计数"), "aligned_corrected": ("matrix", "对齐后的校正层"),
    "audit": ("TSV", "捕获及基因交集统计"), "expression": ("matrix", "归一化对数表达"),
    "hvg": ("boolean vector", "高变基因掩码"), "pca": ("matrix", "主成分坐标"),
    "representation": ("matrix", "实际建图坐标"), "variance": ("TSV", "主成分解释方差"),
    "graph": ("sparse matrix", "邻居连通权重"), "distances": ("sparse matrix", "邻居距离"),
    "embedding": ("matrix", "UMAP 坐标"), "labels": ("categorical[]", "各分辨率簇成员"),
    "comparison": ("TSV[]", "稳定性、重叠与样本构成"), "products": ("file[]", "任务产物"),
    "environment": ("JSON", "软件环境"), "parameters": ("JSON", "有效参数及参考"),
    "source": ("H5AD", "来源计算对象"), "component_object": ("H5AD", "本模块的交接对象"),
    "checkpoint": ("H5AD", "已清洗的对象"), "object": ("H5AD", "注释前分析对象"),
    "libraries": ("capture[]", "各物理捕获的输入"), "parent": ("job", "父任务"),
}
# A trailing question mark denotes a conditional port.
INTERFACES = {
    "reads": ("reads", "report"),
    "reference": ("fasta gtf", "index"),
    "quantify": ("reads index whitelist?", "raw counts?"),
    "call": ("raw", "counts calls"),
    "ambient": ("raw counts groups", "corrected rho"),
    "qc": ("counts reference", "metrics"),
    "merge": ("counts metrics corrected?", "merged aligned_corrected? audit"),
    "features": ("merged aligned_corrected?", "expression hvg"),
    "pca": ("expression hvg", "pca representation variance"),
    "graph": ("representation", "graph distances"),
    "umap": ("graph", "embedding"),
    "leiden": ("graph", "labels comparison"),
    "export": ("products parameters", "products environment"),
}
TASKS = {
    "analysis": ("libraries reference parameters", "object products"),
    "quality": ("libraries reference parameters", "checkpoint products"),
    "from_qc": ("parent checkpoint parameters", "object products"),
    "recluster": ("parent object parameters", "object products"),
    "read_qc": ("libraries parameters", "report products"),
    "quantify": ("libraries parameters", "raw counts? products"),
    "build_reference": ("fasta gtf parameters", "index products"),
}
SINGLE_MODULES = ("features", "pca", "graph", "umap", "leiden")
for name in SINGLE_MODULES:
    TASKS[name] = ("parent? source parameters", "component_object products")

PLANT="https://academic.oup.com/plcell/article/36/4/812/7564676"
SCANPY="https://scanpy.readthedocs.io/en/stable/tutorials/basics/clustering.html"
PRACTICE={
    "reads": ("核对 R1/R2、各 lane 与建库记录，分别查看每个读段的技术指标。","https://www.bioinformatics.babraham.ac.uk/projects/fastqc/"),
    "reference": ("FASTA 和 GTF 来自同一组装，索引保留来源指纹。",PLANT),
    "quantify": ("按建库化学选择条码与 UMI 长度，按模态核对内含子。","https://github.com/alexdobin/STAR/blob/2.7.11b/docs/STARsolo.md"),
    "call": ("只在含背景液滴的原始矩阵上估计背景，记录 FDR。","https://doi.org/10.1186/s13059-019-1662-y"),
    "ambient": ("需同一捕获的 raw、候选计数和分群。检查估计污染率，保留整数原始层。","https://doi.org/10.1093/gigascience/giaa151"),
    "qc": ("按物理捕获估计阈值，检查细胞与细胞核差异、细胞器 ID 覆盖和双细胞比例。",PLANT),
    "merge": ("核对物种、模态和稳定基因轴。交集模式须检查丢失的基因和计数。",PLANT),
    "features": ("HVG 方法须与输入层匹配。Seurat v3 使用整数计数，离散度法使用对数表达。",SCANPY),
    "pca": ("检查方差谱及条件和批次的共同支持，整合后复核邻域保留。",SCANPY),
    "graph": ("记录实际 PC 表示、邻居数和随机种子，检查图连通性。",SCANPY),
    "umap": ("UMAP 用于观察结构；分区和稳定性比较基于高维近邻图。",SCANPY),
    "leiden": ("同图比较多个分辨率、不同种子及样本构成，另行审核生物学可解释性。",SCANPY),
    "export": ("回读 H5AD、保留逐细胞追踪信息、参数和软件版本。",PLANT),
}


def _ports(text):
    values=[]
    for token in text.split():
        key=token.rstrip("?")
        kind,label=TYPES[key]
        values.append({"id":key,"type":kind,"label":label,"required":not token.endswith("?")})
    return values


def contract(name,task=False):
    inputs,outputs=(TASKS if task else INTERFACES)[name]
    return {"version":1,"inputs":_ports(inputs),"outputs":_ports(outputs)}


def module_definition(name):
    guidance,source=PRACTICE[name]
    return {"ports":contract(name),"practice":{"review":guidance,"source":source}}


def artifact(path,selector=None):
    obj={"path":str(Path(path).resolve())}
    if selector:obj["selector"]=selector
    return obj


def task_bindings(spec, parameters):
    inputs = {"parameters": [artifact(parameters)]}
    if spec["libraries"]:
        inputs["libraries"] = []
        for lib in spec["libraries"]:
            binding = {"capture": lib["id"], **artifact(lib["path"])}
            binding.update({k: lib[k] for k in ("kind", "sample", "modality", "prefix", "counts_layer",
                                               "raw_path", "filtered_path", "corrected_path", "clusters_tsv", "upstream_job") if lib.get(k)})
            inputs["libraries"].append(binding)
    action = spec["action"]
    if action in ("quality", "analysis"):
        inputs["reference"] = [artifact(parameters, "/reference")]
    if action == "build_reference":
        inputs.update({k: [artifact(spec["params"][k])] for k in ("fasta", "gtf") if spec["params"].get(k)})
    if spec.get("parent_job"):
        inputs["parent"] = [{"value": spec["parent_job"]}]
    for field, port in (("checkpoint_h5ad", "checkpoint"), ("graph_h5ad", "object"), ("source_h5ad", "source")):
        if spec.get(field):
            inputs[port] = [artifact(spec[field])]
    return inputs


def concrete_manifest(base, spec, plan, receipts, inputs, outputs):
    """Validate every required binding. Reference H5AD members without duplicating matrices."""
    import h5py
    from contextlib import ExitStack
    out=base/"results"
    action=spec["action"]
    cfg=spec["params"]
    params=artifact(out/"parameters.json")
    reference=artifact(out/"parameters.json","/reference")
    files=[artifact(r["path"]) for r in outputs]
    report_path=out/"summary.json"
    observed=json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    methods=observed.get("methods",{})
    modules=[]
    hdf={}
    stack=ExitStack()

    def checked(bindings,declared):
        for port in declared:
            values=bindings.get(port["id"],[])
            if port["required"] and not values:
                raise ValueError("缺少模块端口 "+port["id"])
            for value in values:
                if "path" not in value:continue
                path=Path(value["path"])
                if not path.exists():raise ValueError("模块产物不存在："+str(path))
                selector=value.get("selector")
                if selector and path.suffix==".h5ad":
                    if path not in hdf:hdf[path]=stack.enter_context(h5py.File(path,"r"))
                    if selector not in hdf[path]:raise ValueError(f"{path.name} 内缺少 {selector}")
        return bindings

    def matrix_port(path, selection):
        if Path(path).suffix.lower()!=".h5ad":
            return artifact(path)
        from .qc import count_layer_name
        p=Path(path)
        if p not in hdf:
            hdf[p]=stack.enter_context(h5py.File(p,"r"))
        layer=count_layer_name(selection,hdf[p].get("layers",{}))
        return artifact(path,"layers/"+layer if layer else "X")

    def add(name,incoming,outgoing,capture=None,overrides=None):
        form=contract(name)
        block_info=next(b for b in plan["blocks"] if b["id"]==name)
        effective=dict(block_info["parameters"])
        effective.update(overrides or {})
        observed_values={k:methods[k] for k in {"features":("hvg","hvg_method","analysis_layer"),"pca":("integration","pca_components","representation"),"graph":("neighbors","graph_components"),"umap":("min_dist","seed"),"leiden":("selected_resolution","stability")}.get(name,()) if k in methods}
        if name=="qc":observed_values=next((l for l in observed.get("libraries",[]) if l["id"]==capture),{})
        modules.append(dict(module=name,version=block_info["version"],engine=block_info["engine"],capture=capture,parameters=effective,observed=observed_values,
                            inputs=checked(incoming,form["inputs"]),outputs=checked(outgoing,form["outputs"])))

    published={}
    with stack:
        for entry in receipts:
            name=entry["component"]
            capture=entry.get("capture")
            if name=="reads":
                reports=[artifact(p) for p in sorted(Path(entry["report"]).parent.glob("*.html"))]
                incoming={"reads":[artifact(p) for p in entry["plan"]["files"]]}
                outgoing={"report":reports}
            elif name=="reference":
                incoming={k:[artifact(cfg[k])] for k in ("fasta","gtf")}
                outgoing={"index":[artifact(entry["reference_dir"])]}
            elif name=="quantify":
                paths=entry.get("input_fastqs") or entry["plan"]["files"]
                idx=entry.get("index") or entry["plan"]["reference_dir"]
                incoming={"reads":[artifact(p) for p in paths],"index":[artifact(idx)]}
                if entry.get("whitelist"):incoming["whitelist"]=[artifact(entry["whitelist"])]
                outgoing={"raw":[artifact(entry["raw_path"])]}
                if entry.get("filtered_path"):outgoing["counts"]=[artifact(entry["filtered_path"])]
            elif name=="call":
                incoming={"raw":[artifact(entry["raw_path"])]}
                outgoing={"counts":[artifact(entry["filtered_path"])],"calls":[artifact(entry["barcodes_tsv"])]}
            elif name=="ambient":
                incoming={"raw":[artifact(entry["raw_path"])],"counts":[artifact(entry["filtered_path"])],
                          "groups":[artifact(entry["clusters_tsv"])]}
                outgoing={"corrected":[artifact(entry["corrected_path"])],"rho":[{"value":entry["rho"]}]}
            else:raise ValueError("未知的上游模块 "+name)
            add(name,incoming,outgoing,capture)
            for key,items in outgoing.items():published.setdefault(key,[]).extend(items)

        dataset=out/("qc.h5ad" if action=="quality" else "analysis.h5ad")
        def member(slot):return [artifact(dataset,slot)]
        if action in SINGLE_MODULES:
            dataset = out/"component.h5ad"
            stage = observed["stage"]
            add(action,stage["inputs"],stage["outputs"])
        if action in ("analysis","quality"):
            qc_tables=[];counts=[];corrected=[]
            for i,lib in enumerate(spec["libraries"],1):
                native=matrix_port(lib["path"],lib.get("counts_layer"))
                tab=artifact(out/"captures"/f"{i:03d}"/"qc.tsv")
                add("qc",{"counts":[native],"reference":[reference]},{"metrics":[tab]},lib["id"],lib.get("params"))
                qc_tables.append(tab);counts.append(native)
                if lib.get("corrected_path"):corrected.append(matrix_port(lib["corrected_path"],lib.get("corrected_counts_layer")))
            merged=member("X" if action=="quality" else "layers/counts")
            merge_out={"merged":merged,"audit":[artifact(out/"qc_libraries.tsv")]}
            if corrected:merge_out["aligned_corrected"]=member("layers/soupx")
            add("merge",{"counts":counts,"metrics":qc_tables,"corrected":corrected},merge_out)
        if action in ("analysis","from_qc"):
            summary=json.loads((out/"summary.json").read_text(encoding="utf-8"))
            rep=summary["methods"]["representation"]
            source=Path(spec["checkpoint_h5ad"]) if action=="from_qc" else dataset
            incoming={"merged":[artifact(source,"X" if action=="from_qc" else "layers/counts")]}
            if cfg.get("analysis_layer")=="soupx":incoming["aligned_corrected"]=[artifact(source,"layers/soupx")]
            feature={"expression":member("X"),"hvg":member("var/highly_variable")}
            add("features",incoming,feature)
            add("pca",feature,{"pca":member("obsm/X_pca"),"representation":member("obsm/"+rep),"variance":[artifact(out/"pca_variance.tsv")]})
            add("graph",{"representation":member("obsm/"+rep)},{"graph":member("obsp/connectivities"),"distances":member("obsp/distances")})
            add("umap",{"graph":member("obsp/connectivities")},{"embedding":member("obsm/X_umap")})
        if action in ("analysis","from_qc","recluster"):
            from .advanced import label_key
            labels=[artifact(dataset,"obs/"+k) for k in ["leiden","leiden_seed_check",*(label_key(r) for r in cfg["resolutions"])]]
            source=spec["graph_h5ad"] if action=="recluster" else dataset
            add("leiden",{"graph":[artifact(source,"obsp/connectivities")]},
                {"labels":labels,"comparison":[artifact(out/f) for f in ("cluster_comparison.tsv","cluster_membership_overlap.tsv","cluster_samples.tsv")]})

        original=json.loads((base/"request.json").read_text(encoding="utf-8"))
        task_inputs=task_bindings(original,out/"parameters.json")
        task_outputs={"products":files}
        for p in contract(action,True)["outputs"]:
            key=p["id"]
            if key in ("checkpoint","object","component_object"):task_outputs[key]=[artifact(dataset)]
            elif key in published:task_outputs[key]=published[key]
        add("export",{"products":files,"parameters":[params]},{"products":files,"environment":[artifact(out/"execution-environment.json")]})
        form=contract(action,True)
        return {"schema":"plant-task-io/1","action":action,"contract":form,
                "inputs":checked(task_inputs,form["inputs"]),"outputs":checked(task_outputs,form["outputs"]),
                "input_files":inputs,"modules":modules,"parent_job":spec.get("parent_job")}

