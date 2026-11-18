"""Bounded view data for the offline chart viewer; counts are always full-dataset."""
import csv
from collections import Counter
import random
def embedding_table(path,limit=4000):
    rows=[];n=0;rng=random.Random(42);counts={}
    with path.open(encoding="utf-8",newline="") as f:
        data=csv.DictReader(f,delimiter="\t");headers=data.fieldnames or []
        groups=[k for k in headers if k in ("leiden","sample","capture","batch","condition") or k.startswith("leiden_")]
        cols=["cell_id","UMAP1","UMAP2",*groups]
        if not set(cols)<=set(headers):raise ValueError("当前结果缺少完整的工作台嵌入坐标。")
        counts={k:Counter() for k in groups}
        for n,row in enumerate(data,1):
            for k in groups:counts[k][row[k]]+=1
            point=[row[k] for k in cols]
            if n<=limit:rows.append(point)
            else:
                slot=rng.randrange(n)
                if slot<limit:rows[slot]=point
    return {"columns":cols,"groups":groups,"rows":rows,"total":n,"counts":counts}

