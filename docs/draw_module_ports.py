"""Draw the independently runnable stages, annotated with their real AnnData fields."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch

font=FontProperties(fname="C:/Windows/Fonts/msyh.ttc")
fig,ax=plt.subplots(figsize=(13.8,5.1))
fig.patch.set_facecolor("#f7f8f4")
ax.set(xlim=(0,14),ylim=(0,5));ax.axis("off")
fig.subplots_adjust(left=.025,right=.98,top=.99,bottom=.03)
def label(x,y,text,size=12,color="#153a30",face=font):
    ax.text(x,y,text,fontsize=size,fontproperties=face,color=color,ha="left",va="center")
def stage(x,y,title,slot,width):
    ax.add_patch(FancyBboxPatch((x,y),width,.90,boxstyle="round,pad=.02,rounding_size=.09",lw=1.15,
                                fc="white",ec="#a8bfb5",zorder=2))
    label(x+.14,y+.63,title,12)
    ax.text(x+.14,y+.25,slot,fontsize=8.5,family="DejaVu Sans Mono",color="#477467",va="center")
def arrow(start,end):
    ax.annotate("",xy=end,xytext=start,arrowprops=dict(arrowstyle="-|>",mutation_scale=14,color="#4b7c68",lw=1.6))
label(.2,4.52,"从同一张邻居图分别运行 UMAP 和 Leiden",22)
label(.21,4.02,"每个方框是一次可独立保存的计算。字段名对应工作台生成的 H5AD 对象。",11,"#47665a")
stage(.20,2.02,"质控与清洗","qc.h5ad / X",1.87)
stage(2.54,2.02,"归一化与高变基因","X + highly_variable",2.32)
stage(5.35,2.02,"主成分","obsm/X_pca",1.82)
stage(7.67,2.02,"邻居图","obsp/connectivities",2.18)
stage(10.81,2.7,"UMAP 坐标","obsm/X_umap",2.52)
stage(10.81,1.34,"Leiden 分区","obs/leiden",2.52)
for left,right in [(2.07,2.54),(4.86,5.35),(7.17,7.67)]:
    arrow((left,2.47),(right,2.47))
ax.plot([9.85,10.30],[2.47,2.47],color="#4b7c68",lw=1.6)
ax.plot([10.30,10.30],[1.79,3.15],color="#4b7c68",lw=1.6)
for y in (1.79,3.15):arrow((10.30,y),(10.81,y))
ax.axhline(.95,xmin=.015,xmax=.952,lw=.8,color="#c4d1c6")
label(.21,.58,"复核入口",11)
label(1.42,.58,"任务与接口 · 查看来源和字段",10,"#47665a")
label(5.40,.58,"文件管理器 · 打开交接对象",10,"#47665a")
label(9.47,.58,"结果可视化 · 对照图和来源任务",10,"#47665a")
fig.savefig(Path(__file__).with_name("module-ports.png"),dpi=150,facecolor=fig.get_facecolor())

