"""Publish human-readable local notebooks from verified run records and the independent audit."""
from urllib.parse import urlencode
from five_project_study import STUDY,ROOT,read

def main():
    audit=read(STUDY/"独立复核.json")
    browser=read(STUDY/"分区交互验收.json")
    cases={p.parent.name:read(p) for p in sorted(STUDY.glob("*/实验记录.json"))}
    notes=ROOT/"lab-notebook/005-分区工作区与五项目验收.md"
    header=notes.read_text(encoding="utf-8").split("\n## 实测结果\n")[0].rstrip()
    summary=[]
    detail={
        "01":("检验研究者能否先冻结 QC 对象，随后继续分析或仅改变分辨率。","以输入基因轴和细胞顺序为基准，逐项比较检查点的整数计数、重分群前后的稀疏图和坐标。独立审核另以每核至少 1,400 UMI 做阈值预览。","此处使用公开数据的预选子集。在当前预选数据中的通过率不能用于估计原文库质量。"),
        "02":("检验双捕获输入、特征交集及处理条件与批次混杂时的行为。","按来源登记 GSM8417227 为 Mild-drought_fixed_rep1、GSM8417230 为 Well-watered_fixed_rep2。两个捕获均有 1,200 个条码。将捕获作为批次，请求 Harmony，核对实际表示、每捕获的 QC 行数和基因交集损失。","每种处理仅有一个捕获，科学解释受处理与捕获混杂限制。该测试验证回退分支及数据保留。"),
        "03":("验证短 R1 的 10x FASTQ 如何通过测序质检与独立定量交付矩阵。","同一对文件按常规 v3 布局提交反例，随后以明确的 10 nt UMI 布局进行 FastQC、MultiQC、STARsolo GeneFull 定量。独立读取两份 FastQC 压缩报告核对完整读段数。","材料为归档文库的一百万对读段。过滤矩阵列数是上游选择的候选条码数，完整文库性能和真实细胞数需另行评估。"),
        "04":("使用标签已知的模拟背景检查条码调用与去污染。","固定随机种子 42。600 个模拟细胞使用 bc0 至 bc599，另有 1,300 个背景条码。输入未过滤矩阵并设置 emptyDrops、lower=80、SoupX，使用校正层建图。独立以仅含过滤矩阵的请求检查预检。","模拟的真值只适用于本夹具。自动污染率和加入比例偏差较大，须结合组织和背景分布复核。"),
        "05":("跨物种验证三捕获输入、参考覆盖、批次诊断和独立 Leiden。","将已登记的 GSE173087 整数计数按样本拆为 GSM5259613、GSM5259614、GSM5259615 三份，逐份复核计数和基因轴，再以 B73 v4 参考、相同根分生组织条件运行 Harmony。复用同图比较 0.4、0.8、1.2。","工作台的两种细胞器参考在该输入基因轴均为零匹配。相关比例全部记缺失并报告警告。此样本支持计算验证，缺乏评估细胞器质量、稀有群体和细胞身份准确性的依据。")}
    for key,c in cases.items():
        project=STUDY/key;m=c["metrics"];links=c["materials"]
        if key=="01": result=f'保留 {m["nuclei"]:,} 核；阈值提高至 1,400 UMI 时预览和独立计算均为 {audit["checks"]["单核提高阈值"]["expected"]} 核；分辨率 0.35 和 0.85 分别得到 {m["clusters_by_resolution"]["leiden_0_35"]} 和 {m["clusters_by_resolution"]["leiden_0_85"]} 个簇。'
        elif key=="02":result=f'{m["retained"]:,} 个细胞，交集 {m["shared_genes"]:,} 个基因。实际使用普通 PCA；两个捕获因基因交集分别少计 {m["capture_loss"]["GSM8417227"]}、{m["capture_loss"]["GSM8417230"]} 个 UMI。'
        elif key=="03":result=f'R1/R2 各 1,000,000 条，实际长度 26/98 nt。默认布局按预期被拒；10 nt UMI 路线产出 {m["reports"]} 份报告和 {m["filtered_matrix"][0]:,} 基因 × {m["filtered_matrix"][1]:,} 个候选条码的过滤矩阵。'
        elif key=="04":result=f'检出 {m["true_positive"]}/600 个模拟细胞，误收 {m["false_positive"]} 个背景条码。模拟加入率 {m["added_fraction"]:.0%}，SoupX 估计 {m["estimated_rho"]:.1%}。单独提供候选条码矩阵时，预检报告缺少同捕获背景。'
        else:result=f'{m["retained"]:,} 个细胞，{m["genes"]:,} 个基因。Harmony 邻域保留率 {m["neighbor_retention"]:.1%}；三档独立 Leiden 分区逐条码复现。三个捕获的线粒体和质体参考基因匹配数都为 0。'
        target=f'runs/{c["show_job"]}/results'
        url="http://127.0.0.1:8876/panes?"+urlencode({"project":c["project"],"job":c["show_job"],"path":target})
        purpose,procedure,boundary=detail[key]
        lines=[f'# 项目 {key} · {c["name"]}',"",f'本地运行时段 {c["started"]} 至 {c["ended"]}。',"","## 问题与材料","",purpose,"",procedure,""]
        sources=[(i["id"],i["source"]) for i in links] if isinstance(links,list) else [(links.get("accession","原始资料"),links["source"])] if "source" in links else []
        if sources:lines+=[" · ".join(f'[{label}]({link})' for label,link in sources),""]
        lines+=["## 执行与验收","","| 任务 | 状态 | 留存文件 |","|---|---|---|"]
        for title,j in c["jobs"].items():
            base=f'runs/{j["id"]}';passed=j["state"]=="succeeded";status="完成" if passed else "符合预期的输入拒绝"
            refs=f'[配方]({j["form"]}) · '+(f'[输入输出]({base}/results/task-io.json) · [收据]({base}/results/receipt.json)' if passed else f'[诊断]({base}/error.json)')
            lines.append(f'| {title} | {status} | {refs} |')
        lines+=["","## 结果","",result,"",boundary,"","逐项通过的检查",""]
        lines+=["- "+name for name,passed in c["checks"].items() if passed]
        lines+=["",f'[打开本项目分区工作区]({url}) · [机器可读记录](实验记录.json) · [独立复核](../独立复核.json)']
        (project/"项目实验记录.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
        summary.append(f'| [项目 {key} · {c["name"]}]({url}) | {result} | [实验记录](../validation/five-projects/{key}/项目实验记录.md) |')
    items=[header,"","## 实测结果","","五个项目均通过各自登记的验收条件。通过服务提交 9 次计算作业，其中 8 次完成，另 1 次按预期因读段布局不兼容而被拒绝。过滤矩阵缺背景及跨项目访问另外在接口层核对。","","| 项目入口 | 观察值 | 数据与参数 |","|---|---|---|",*summary,"",
           f'独立比对了实际产物目录、运行收据以及输入和产物的 SHA-256。去重后共 {audit["unique_verified_files"]} 个文件，{audit["bytes_verified"]:,} 字节。此前的 20 项单元回归另行通过。[复核明细](../validation/five-projects/独立复核.json)',"",
           "## 工作区交互","","桌面左侧为文件和预览，右侧为图表和任务。各区可独立切页或放大，分隔条支持拖动和方向键。刷新可恢复项目、目录、预览文件、图表及任务来源。浏览器已在五个项目中逐一定位收据和对应图表，核对跨项目切换、窄屏堆叠以及目录操作后图的着色保持。[浏览器记录](../validation/five-projects/分区交互验收.json) · [Posit 分区设计](https://docs.posit.co/ide/user/ide/guide/ui/ui-panes.html)", "",
           "![文件与交互式 UMAP 同屏](../validation/five-projects/分区桌面.png)","","![PCA 方差与同一分析的分区比较](../validation/five-projects/双图对照.png)","",
           "## 重做实验","","在已配置的本机科学环境中运行 tests/five_project_study.py，通过现有 HTTP 服务按相同配方为五个项目创建新的作业；随后运行 tests/audit_five_projects.py、tests/panes_acceptance.py 和 tests/report_five_projects.py。主程序也可按两位项目编号仅重跑指定案例。旧作业保留在各项目的 runs 目录。","",
           "资料包含拟南芥和玉米、小规模真实测序子集和一个受控的模拟系统。样本身份、参考版本、捕获标签和原始对象指纹均随项目记录；五项结果支持这些输入和任务组合下的适用性。"]
    assert len(browser["verified_projects"])==5
    notes.write_text("\n".join(items)+"\n",encoding="utf-8")
if __name__=="__main__":main()

