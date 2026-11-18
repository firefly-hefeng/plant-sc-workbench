"""Prepare one integer-count H5AD per explicitly declared physical capture."""
import argparse
import json
from pathlib import Path
import tempfile
import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from .qc import count_layer_name


def split_captures(obj, outdir, capture_key="capture", counts_layer=None, modality=None, batch_from_capture=False):
    if capture_key not in obj.obs:
        raise ValueError(f"找不到指定的物理捕获字段 {capture_key}")
    captures=obj.obs[capture_key].astype("string")
    if captures.isna().any() or captures.str.strip().eq("").any() or not len(captures):
        raise ValueError("每行须有明确的物理捕获编号")
    if captures.str.strip().ne(captures).any():
        raise ValueError("物理捕获编号不能含首尾空格")
    layer=count_layer_name(counts_layer,obj.layers)
    if layer and layer not in obj.layers:
        raise ValueError("缺少所选原始计数层")
    if not layer and "log1p" in obj.uns:
        raise ValueError("请选择原始整数 counts 层")
    x=sparse.csr_matrix(obj.layers[layer] if layer else obj.X)
    if not obj.var_names.is_unique or not np.isfinite(x.data).all() or (x.data<0).any() or (
            not np.issubdtype(x.dtype,np.integer) and (x.data!=np.floor(x.data)).any()):
        raise ValueError("基因标识须唯一，捕获拆分需要非负有限的整数计数")
    out=Path(outdir).resolve()
    if out.exists():
        raise ValueError("请选择新的分捕获结果目录")
    out.parent.mkdir(parents=True,exist_ok=True)
    libraries=[]
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        staged=Path(tmp)/"captures"
        staged.mkdir()
        for i,identifier in enumerate(sorted(captures.unique()),1):
            if ":" in identifier or "/" in identifier or "\\" in identifier:
                raise ValueError("捕获编号不能含冒号或路径分隔符，请先使用明确的文库编号")
            positions=np.flatnonzero(captures.eq(identifier).to_numpy(dtype=bool))
            obs=obj.obs.iloc[positions].copy()
            if not obs.index.is_unique:
                raise ValueError(f"捕获 {identifier} 内的条码重复")
            record=dict(id=identifier,path=str(out/f"{i:03d}.h5ad"),kind="h5ad")
            for field in ("sample","batch","condition","modality"):
                fallback="unspecified"
                if field=="sample" or (field=="batch" and batch_from_capture):
                    fallback=identifier
                if field=="modality" and modality:
                    fallback=modality
                if field not in obs:
                    record[field]=fallback
                    continue
                values=obs[field].astype("string").fillna("unspecified").str.strip().replace("","unspecified").unique()
                if len(values)>1:
                    raise ValueError(f"捕获 {identifier} 的 {field} 含多个值，当前每库设计不能表示这种混样")
                record[field]=str(values[0])
            if capture_key!="capture":
                if "capture" in obs and obs["capture"].astype(str).nunique(dropna=False)>1:
                    raise ValueError("所选字段与已有物理捕获分组冲突")
                obs["capture"]=identifier
            ad.AnnData(x[positions],obs=obs,var=obj.var.copy()).write_h5ad(staged/f"{i:03d}.h5ad",compression="lzf")
            libraries.append(record)
        (staged/"libraries.json").write_text(json.dumps(libraries,ensure_ascii=False,indent=2),encoding="utf8")
        staged.rename(out)
    return libraries


def split_file(path,outdir,capture_key="capture",counts_layer=None,modality=None,batch_from_capture=False):
    return split_captures(ad.read_h5ad(path),outdir,capture_key,counts_layer,modality,batch_from_capture)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--capture-key",default="capture")
    parser.add_argument("--counts-layer")
    parser.add_argument("--modality",choices=("scRNA","snRNA"))
    parser.add_argument("--batch-from-capture",action="store_true")
    a=parser.parse_args()
    print(json.dumps(split_file(a.input,a.out,a.capture_key,a.counts_layer,a.modality,a.batch_from_capture),ensure_ascii=False))


if __name__=="__main__":
    main()

