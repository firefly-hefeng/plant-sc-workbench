"""Graph computation, split/merge diagnostics and publication-ready data views."""
from __future__ import annotations

from collections import OrderedDict
import itertools

import numpy as np
import pandas as pd
from scipy import sparse
from .blocks import block


def label_key(resolution):
    return "leiden_" + str(float(resolution)).replace(".", "_")


@block("graph")
def build_graph(obj, cfg, rep):
    import scanpy as sc
    k = min(cfg["n_neighbors"], obj.n_obs - 1)
    transformer = None
    if obj.n_obs >= 8192:
        from pynndescent import PyNNDescentTransformer

        class CompleteNeighbors(PyNNDescentTransformer):
            """Keep one explicit self-neighbor as expected by Scanpy/UMAP."""
            def fit_transform(self, X, y=None, **fit_params):
                self.fit(X, compress_index=False)
                ids, dist = self.index_.neighbor_graph
                ids, dist = ids.copy(), dist.copy()
                n, ncols = ids.shape
                if ncols < k or (ids < 0).any():
                    raise ValueError("近邻图不完整；请减小邻居数或检查相同坐标的细胞")
                rows = np.arange(n)
                same = ids == rows[:, None]
                slot = np.where(same.any(axis=1), same.argmax(axis=1), ncols - 1)
                ids[rows, slot], dist[rows, slot] = rows, -1
                order = np.argsort(dist, axis=1, kind="stable")[:, :k]
                ids, dist = np.take_along_axis(ids, order, 1), np.take_along_axis(dist, order, 1)
                dist[:, 0] = 0
                return sparse.csr_matrix((dist.ravel(), ids.ravel(), np.arange(0, n*k + 1, k)), shape=(n, n))

        transformer = CompleteNeighbors(n_neighbors=k, random_state=cfg["seed"], n_jobs=1,
                                       n_trees=min(64, 5 + round(obj.n_obs**.5/20)),
                                       n_iters=max(5, round(np.log2(obj.n_obs))))
    sc.pp.neighbors(obj, n_neighbors=k, use_rep=rep, random_state=cfg["seed"], transformer=transformer)
    return k


def _neighbor_profile(coords, obs):
    from sklearn.neighbors import NearestNeighbors
    k = min(15, len(obs) - 1)
    neighbors = NearestNeighbors(n_neighbors=k, n_jobs=1).fit(coords).kneighbors(return_distance=False)
    groups = obs["batch"].astype(str).to_numpy()
    conditions = obs["condition"].astype(str).to_numpy()
    return neighbors, {"batch_mixing": float((groups[neighbors] != groups[:, None]).mean()),
                       "condition_agreement": float((conditions[neighbors] == conditions[:, None]).mean())}


@block("features")
def prepare_features(obj, cfg):
    import scanpy as sc
    if obj.n_obs < 10 or obj.n_vars < 3:
        raise ValueError("建图至少需要 10 个通过初筛的细胞和 3 个基因")
    obj.layers["counts"] = obj.X.copy()
    layer = cfg.get("analysis_layer", "counts")
    if layer not in {"counts", "soupx"} or layer not in obj.layers:
        raise ValueError("所选分析层不可用，请选择 counts 或具备来源的 soupx 层")
    obj.X = obj.layers[layer].astype(np.float32).copy()
    if (np.asarray(obj.X.sum(axis=1)).ravel() == 0).any():
        raise ValueError("选定分析层含有零计数细胞，请核对校正结果")
    sc.pp.normalize_total(obj, target_sum=cfg["target_sum"])
    sc.pp.log1p(obj)
    # Select HVGs from the declared expression layer without erasing non-HVGs.
    detect = obj.layers[layer].getnnz(axis=0) >= max(1, int(cfg.get("min_cells_per_gene", 1)))
    if detect.sum() < 3:
        raise ValueError("符合检出条件的基因不足以做 PCA")
    tmp = obj[:, detect].copy()
    flavor = cfg.get("hvg_method", "seurat")
    if flavor not in ("seurat", "seurat_v3"):
        raise ValueError("hvg_method 可选 seurat 或 seurat_v3")
    batch_key = "batch" if cfg.get("batch_hvg", False) and obj.obs.batch.nunique() > 1 else None
    if flavor == "seurat_v3" and (tmp.layers[layer].data != np.floor(tmp.layers[layer].data)).any():
        raise ValueError("seurat_v3 要求整数 UMI 层，请改用 seurat 或原始计数")
    if cfg["hvg"] >= tmp.n_vars:
        selected = np.ones(tmp.n_vars, bool)
        hvg_effective = "all_detected_features"
    else:
        sc.pp.highly_variable_genes(tmp, flavor=flavor, layer=layer if flavor=="seurat_v3" else None,
                                    n_top_genes=cfg["hvg"], batch_key=batch_key)
        selected = tmp.var["highly_variable"].to_numpy()
        hvg_effective = flavor
        for column in ("means", "dispersions_norm", "variances_norm", "highly_variable_nbatches"):
            if column in tmp.var:
                obj.var[column] = tmp.var[column].reindex(obj.var_names)
    obj.var["highly_variable"] = False
    obj.var.loc[tmp.var_names[selected], "highly_variable"] = True
    del tmp
    return selected, hvg_effective, layer


@block("pca")
def build_representation(obj, cfg, out, selected, warnings):
    import scanpy as sc
    components = min(cfg["n_pcs"], obj.n_obs-1, int(selected.sum())-1)
    if components < 2:
        raise ValueError("可用变异基因不足，请调整 HVG 参数")
    sc.pp.pca(obj, n_comps=components, mask_var="highly_variable", svd_solver="arpack", random_state=cfg["seed"])
    if not np.isfinite(obj.obsm["X_pca"]).all() or np.max(obj.uns["pca"]["variance"]) <= 0:
        raise ValueError("表达矩阵缺少可用于建图的变异")
    pd.DataFrame({"PC": np.arange(1,components+1), "variance":obj.uns["pca"]["variance"],
                  "proportion":obj.uns["pca"]["variance_ratio"]}).to_csv(out/"pca_variance.tsv",sep="\t",index=False)
    rep = "X_pca"
    integration = {"status": "not_requested", "selected": rep}
    if cfg["integration"] == "harmony":
        table = pd.crosstab(obj.obs.batch, obj.obs.condition)
        unknown = {"", "unspecified", "unknown", "na", "n/a", "nan", "none"}
        incomplete = any(obj.obs[key].astype("string").fillna("").str.strip().str.lower().isin(unknown).any()
                         for key in ("batch", "condition"))
        if incomplete or len(table) < 2 or (table == 0).any().any() or obj.n_obs < 100:
            integration["status"] = "ineligible"
            warnings.append("批次或条件未知、批次少于两个、处理缺乏共同支持或细胞少于 100 个，使用未整合 PCA")
        else:
            import harmonypy
            result = harmonypy.run_harmony(obj.obsm["X_pca"], obj.obs, "batch", random_state=cfg["seed"],
                                           nclust=max(2,min(100,round(obj.n_obs/30))), verbose=False)
            corrected = np.asarray(result.Z_corr)
            if corrected.shape == (components, obj.n_obs):
                corrected = corrected.T
            if corrected.shape != (obj.n_obs,components) or not np.isfinite(corrected).all():
                raise ValueError("Harmony 返回的表示与输入细胞轴不一致")
            rep = "X_pca_harmony"
            obj.obsm[rep] = corrected.astype(np.float32)
            before_ids, before = _neighbor_profile(obj.obsm["X_pca"], obj.obs)
            after_ids, after = _neighbor_profile(obj.obsm[rep], obj.obs)
            overlap = np.mean([len(set(a)&set(b))/len(a) for a,b in zip(before_ids,after_ids)])
            integration = {"status": "computed", "selected": rep, "before":before,"after":after,"neighbor_retention":float(overlap)}
            warnings.append("Harmony 诊断仅衡量局部邻域和批次混合，须结合组织与条件复核")
    return rep, components, integration


@block("umap")
def embed_graph(obj, cfg):
    import scanpy as sc
    # umap-learn can zero low-weight edges in its working sparse buffer.
    # Leiden and subsequent consumers must receive the unmodified neighbor graph.
    graph_key = obj.uns["neighbors"].get("connectivities_key", "connectivities")
    graph = obj.obsp[graph_key]
    obj.obsp[graph_key] = graph.copy()
    try:
        sc.tl.umap(obj, min_dist=cfg["min_dist"], random_state=cfg["seed"])
    finally:
        obj.obsp[graph_key] = graph
    if not np.isfinite(obj.obsm["X_umap"]).all():
        raise ValueError("UMAP 含非有限坐标")


def graph_representation(automatic, cfg):
    choice=cfg.get("graph_representation","auto")
    if choice not in ("auto","X_pca","X_pca_harmony"):
        raise ValueError("图表示应为 auto、X_pca 或 X_pca_harmony")
    return automatic if choice=="auto" else choice

def reduce_and_cluster(obj, cfg, out, progress, warnings):
    from scipy.sparse.csgraph import connected_components
    selected, hvg_effective, layer = prepare_features(obj, cfg)
    rep, components, integration = build_representation(obj, cfg, out, selected, warnings)
    rep=graph_representation(rep,cfg)
    if rep not in obj.obsm:
        raise ValueError("所选建图表示未生成，请核对整合资格或选择原始 PCA")
    progress(64, "计算邻居图、Leiden 分区和 UMAP")
    k = build_graph(obj, cfg, rep)
    embed_graph(obj, cfg)
    main, comparison = cluster_partitions(obj,cfg,out)
    return {"hvg":int(selected.sum()), "hvg_method":hvg_effective, "pca_components":components,"neighbors":k,
            "selected_resolution":main, "graph_components":int(connected_components(obj.obsp["connectivities"],directed=False)[0]),
            "representation":rep,"analysis_layer":layer,"integration":integration,"stability":comparison}


@block("leiden")
def cluster_partitions(obj, cfg, out, *, adjacency=None):
    import scanpy as sc
    from sklearn.metrics import adjusted_rand_score
    labels = OrderedDict()
    for r in cfg["resolutions"]:
        key = label_key(r)
        sc.tl.leiden(obj, resolution=r, key_added=key, adjacency=adjacency, flavor="igraph", n_iterations=2,
                     directed=False, random_state=cfg["seed"])
        labels[key] = obj.obs[key].astype(str)
    main = float(cfg.get("selected_resolution", cfg["resolutions"][0]))
    if main not in cfg["resolutions"]:
        raise ValueError("选定的主分辨率须包含在比较列表中")
    obj.obs["leiden"] = obj.obs[label_key(main)].copy()
    seed_key = "leiden_seed_check"
    sc.tl.leiden(obj, resolution=main, key_added=seed_key, adjacency=adjacency, flavor="igraph", directed=False,
                 n_iterations=2, random_state=(cfg["seed"]+1) % (2**31-1))
    comparison, overlap_rows = [], []
    for a,b in list(itertools.combinations(labels,2)) + [(label_key(main), seed_key)]:
        v1, v2 = obj.obs[a].astype(str), obj.obs[b].astype(str)
        table = pd.crosstab(v1,v2)
        comparison.append({"left":a,"right":b,"left_clusters":v1.nunique(),"right_clusters":v2.nunique(),
                           "ARI":float(adjusted_rand_score(v1,v2))})
        for ix,jx in zip(*np.nonzero(table.values)):
            n = int(table.iat[ix,jx])
            overlap_rows.append({"left":a,"right":b,"left_cluster":str(table.index[ix]),
                                 "right_cluster":str(table.columns[jx]), "shared":n,
                                 "jaccard":n/(table.iloc[ix].sum()+table.iloc[:,jx].sum()-n)})
    pd.DataFrame(comparison).to_csv(out/"cluster_comparison.tsv", sep="\t",index=False)
    pd.DataFrame(overlap_rows).to_csv(out/"cluster_membership_overlap.tsv", sep="\t",index=False)
    pd.crosstab(obj.obs.leiden,obj.obs["sample"]).to_csv(out/"cluster_samples.tsv", sep="\t")
    return main, comparison


def figures(obj, qc, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(42)
    def save(fig, stem):
        fig.tight_layout()
        fig.savefig(out/(stem+".png"), dpi=145, bbox_inches="tight")
        fig.savefig(out/(stem+".svg"), bbox_inches="tight")
        plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(9,3.9))
    for keep,color,name in ((False,"#c97644","Excluded"),(True,"#227963","Retained")):
        block=qc[qc.retained.eq(keep)]
        if len(block)>30000:
            block=block.iloc[rng.choice(len(block),30000,replace=False)]
        axes[0].scatter(block.total_counts,block.n_genes,s=6,alpha=.45,c=color,label=name,rasterized=True)
    axes[0].set(xlabel="UMI counts per barcode",ylabel="Detected genes",xscale="symlog",yscale="symlog")
    axes[0].legend(frameon=False)
    total=qc.groupby("capture",observed=True).size()
    kept=qc.groupby("capture",observed=True).retained.sum()
    idx=np.arange(len(total))
    axes[1].bar(idx,kept,color="#227963",label="Retained")
    axes[1].bar(idx,total-kept,bottom=kept,color="#c97644",label="Excluded")
    axes[1].set_xticks(idx, ["L"+str(i+1) for i in idx], rotation=45 if len(idx)>6 else 0)
    axes[1].set(xlabel="Capture (see qc_libraries.tsv for L-index)",ylabel="Barcodes")
    for ax in axes:
        ax.spines[["top","right"]].set_visible(False)
    save(fig,"qc")
    if obj is None:
        return
    xy=obj.obsm["X_umap"]
    ix=rng.choice(len(xy),min(len(xy),50000),replace=False)
    fig,axes=plt.subplots(1,2,figsize=(10,4.5))
    for axis,key,title in zip(axes,("leiden","capture"),("Leiden clusters","Capture libraries")):
        codes,groups=pd.factorize(obj.obs[key].astype(str),sort=True)
        axis.scatter(xy[ix,0],xy[ix,1],s=4,c=codes[ix],cmap="tab20",alpha=.76,rasterized=True)
        if len(groups)<=25:
            for j,g in enumerate(groups):
                xyj=xy[codes==j]
                med=np.median(xyj,axis=0)
                label=str(g) if key=="leiden" else "L"+str(j+1)
                axis.annotate(label,med,fontsize=8,ha="center",bbox={"fc":"white","ec":"none","alpha":.7,"pad":1})
        axis.set(title=title,xlabel="UMAP 1",ylabel="UMAP 2")
        axis.spines[["top","right"]].set_visible(False)
    save(fig,"embedding")
    variance=np.asarray(obj.uns["pca"]["variance_ratio"])
    fig,axis=plt.subplots(figsize=(6.6,3.8))
    axis.plot(np.arange(1,len(variance)+1),100*variance,marker="o",markersize=3,color="#237f67")
    axis.set(xlabel="Principal component",ylabel="Explained variance (%)",title="PCA variance")
    axis.spines[["top","right"]].set_visible(False)
    save(fig,"pca")
    comp=pd.read_csv(out/"cluster_comparison.tsv",sep="\t").iloc[0]
    tab=pd.crosstab(obj.obs[comp.left],obj.obs[comp.right])
    # Large partitions retain full counts in the TSV; the preview shows the largest groups.
    top_r=tab.sum(axis=1).nlargest(25).index
    top_c=tab.sum(axis=0).nlargest(25).index
    tab=tab.loc[top_r,top_c]
    fig,axis=plt.subplots(figsize=(6.7,5.0))
    plot=axis.imshow(tab.to_numpy(),aspect="auto",interpolation="nearest",cmap="BuGn")
    axis.set_xticks(np.arange(len(tab.columns)),tab.columns.astype(str),rotation=60)
    axis.set_yticks(np.arange(len(tab.index)),tab.index.astype(str))
    axis.set(xlabel=comp.right,ylabel=comp.left,title=f"Shared barcodes (ARI {comp.ARI:.3f})")
    fig.colorbar(plot,ax=axis,label="Shared cells")
    save(fig,"cluster_comparison")
