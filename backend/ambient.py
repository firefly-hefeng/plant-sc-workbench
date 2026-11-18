"""Prepare the optional within-capture rough groups used by SoupX."""
from pathlib import Path
import numpy as np
import pandas as pd
def provisional_groups(filtered_path, directory, seed):
    import scanpy as sc
    from .qc import read_counts
    obj=read_counts(filtered_path)
    if obj.n_obs<50:raise ValueError("该捕获不足 50 个候选条码，自动分组不稳定；请提供粗分组或关闭校正。")
    if (np.asarray(obj.X.sum(axis=1)).ravel()==0).any():raise ValueError("候选矩阵仍含空条码，请复核条码名单。")
    sc.pp.normalize_total(obj,target_sum=10000)
    sc.pp.log1p(obj)
    # Dense centering is avoided for the full feature matrix.
    detect=np.asarray((obj.X>0).sum(axis=0)).ravel()>=3
    obj=obj[:,detect].copy()
    if obj.n_vars<4:raise ValueError("有效基因不足，无法生成临时分组。")
    if obj.n_vars>2000:sc.pp.highly_variable_genes(obj,n_top_genes=2000,flavor="seurat",subset=True)
    sc.pp.pca(obj,n_comps=min(20,obj.n_obs-1,obj.n_vars-1),random_state=seed)
    sc.pp.neighbors(obj,use_rep="X_pca",n_neighbors=min(15,obj.n_obs-1),random_state=seed)
    sc.tl.leiden(obj,flavor="igraph",directed=False,n_iterations=2,resolution=0.5,random_state=seed)
    if obj.obs.leiden.nunique()<2:raise ValueError("临时分组只得到一个簇，自动估计缺乏依据。请复核或关闭校正。")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    output=directory/"provisional_groups.tsv"
    pd.DataFrame({"barcode":obj.obs_names,"cluster":obj.obs.leiden.to_numpy()}).to_csv(output,index=False,sep="\t")
    return str(output)

