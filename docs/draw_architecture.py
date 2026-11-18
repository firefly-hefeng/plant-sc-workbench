"""Rebuild the execution and data flow figure in the design document."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.font_manager import FontProperties

font_path=Path("C:/Windows/Fonts/msyh.ttc")
font=FontProperties(fname=str(font_path)) if font_path.is_file() else FontProperties(family="sans-serif")
fig,ax=plt.subplots(figsize=(14,8),layout="constrained")
ax.set(xlim=(0,14),ylim=(0,8));ax.axis("off")
fig.set_facecolor("#fbfaf6")
def label(x,y,text,size,color="#163c37",ha="left",bold=False):
    ax.text(x,y,text,ha=ha,va="center",fontproperties=font,fontsize=size,color=color,
            weight="bold" if bold else "normal")
def box(x,y,width,height,title,sub,fill="#ffffff",stroke="#a9c0b6"):
    ax.add_patch(FancyBboxPatch((x,y),width,height,boxstyle="round,pad=0.025,rounding_size=0.12",
                 facecolor=fill,edgecolor=stroke,lw=1.3))
    label(x+.20,y+height*.67,title,13,bold=True);label(x+.20,y+height*.28,sub,9,"#44645c")
def arrow(x1,y1,x2,y2):
    ax.annotate("",xy=(x2,y2),xytext=(x1,y1),arrowprops=dict(arrowstyle="-|>",color="#54786c",lw=1.6,
                shrinkA=1,shrinkB=2,mutation_scale=13))
label(.25,7.55,"植物单细胞工作台的模块与数据交接",24,bold=True)
label(.27,7.08,"从本地输入到可复查的聚类对象",12,"#536c63")
box(.3,5.72,3.05,.95,"图形工作台","选择文件、预览质控、调整参数","#e0eee7")
box(4.05,5.72,4.9,.95,"共享配方与计算块","按文库角色、参考版本、参数和工具状态生成方案","#cde5d8")
box(9.65,5.72,3.9,.95,"DeepSeek Harness","通过本地 MCP 调用同一组工具","#e0eee7")
arrow(3.39,6.2,4.01,6.2);arrow(9.60,6.2,9.00,6.2)
label(.27,5.27,"数据入口",12,bold=True)
box(.3,4.15,3.75,.88,"成对 FASTQ","FastQC / MultiQC → STARsolo 或 Cell Ranger")
box(5.05,4.15,3.75,.88,"原始液滴矩阵","上游条码或 emptyDrops；可选 SoupX")
box(9.8,4.15,3.75,.88,"候选细胞计数","10x MEX、H5 或含原始计数的 H5AD")
arrow(4.08,4.58,5.00,4.58);arrow(8.83,4.58,9.75,4.58)
arrow(11.65,4.12,11.65,3.61)
box(9.8,2.66,3.75,.92,"捕获级质控与清洗","UMI、检测基因、细胞器比例、双细胞","#edf1e1")
box(5.05,2.66,3.75,.92,"归一化与降维","对齐基因轴、HVG、PCA，可选 Harmony","#edf1e1")
box(.3,2.66,3.75,.92,"近邻图","选择表示、主成分数与邻居数","#edf1e1")
arrow(9.75,3.12,8.83,3.12);arrow(5.00,3.12,4.08,3.12)
arrow(2.14,2.62,2.14,2.10)
box(.3,1.11,3.75,.95,"UMAP 与 Leiden","同图嵌入、多个分辨率、成员和稳定性")
box(5.05,1.11,3.75,.95,"注释前交接对象","保留原始计数、坐标、图、分群和元数据")
box(9.8,1.11,3.75,.95,"文件与图像查看器","浏览项目、比较方案、放大图像和查看表格")
arrow(4.08,1.58,5.00,1.58);arrow(8.83,1.58,9.75,1.58)
label(.27,.47,"运行记录",12,bold=True)
label(1.52,.47,"输入校验值  /  参考集与软件版本  /  参数快照  /  模块事件  /  H5AD 回读与结果收据",11,"#45645a")
fig.savefig(Path(__file__).with_name("architecture.png"),dpi=155,facecolor=fig.get_facecolor())

