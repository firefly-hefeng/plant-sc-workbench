"""Bounded previews for scientific files. Counts and matrix layers stay on disk."""
import codecs
import csv
import gzip
import io
from itertools import islice
import json
from pathlib import Path
import zipfile

LIMIT = 128 * 1024
ROWS = 100
TEXT = set(".txt .log .out .stats .md .markdown .json .jsonl .yaml .yml .py .r .sh .ps1 .toml .ini .cfg .html .htm .svg .xml .mtx .fastq .fq .fasta .fa .fna .gtf .gff .gff3 .bed .sam .vcf .rmd .rproj".split())


def hdf_preview(path):
    import h5py

    def local(group, key):
        if isinstance(group, h5py.Group) and isinstance(group.get(key, getlink=True), h5py.HardLink):
            return group[key]

    rows = []
    with h5py.File(path, "r") as f:
        matrix = local(f, "X")
        if isinstance(matrix, h5py.Dataset):
            shape = matrix.shape
        else:
            shape = matrix.attrs.get("shape") if isinstance(matrix, h5py.Group) else None
        if shape is not None and len(shape) == 2:
            rows.append(["表达矩阵 X", f"{shape[0]:,} 个细胞或细胞核 × {shape[1]:,} 个基因或特征"])
        tenx = local(local(f, "matrix"), "shape")
        if isinstance(tenx, h5py.Dataset) and tenx.shape == (2,) and tenx.dtype.kind in "iu":
            genes, barcodes = tenx[:]
            rows.append(["10x 计数矩阵", f"{genes:,} 个特征 × {barcodes:,} 个条码"])
        truncated = len(f) > 30
        for key in islice(f, 30):
            obj = local(f, key)
            if isinstance(obj, h5py.Dataset):
                detail = f"{obj.shape} · {obj.dtype}"
            elif isinstance(obj, h5py.Group):
                names = list(islice(obj, 20))
                detail = "、".join(names) or "空分组"
                if len(obj) > len(names):
                    detail += f" …（共 {len(obj)} 项）"
            else:
                detail = "链接"
            rows.append(["/" + key, detail])
    return {"columns": ["对象位置", "维度或字段"], "rows": rows, "truncated": truncated,
            "note": "对象结构预览。X 保存表达矩阵，obs 保存细胞信息，var 保存基因信息。" if shape is not None else "HDF5 文件的顶层结构。"}


def parquet_preview(path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    with pq.ParquetFile(path, thrift_string_size_limit=8_000_000, thrift_container_size_limit=200_000) as file:
        schema = file.schema_arrow
        result = {"columns": ["字段", "数据类型"], "rows": [[f.name, str(f.type)] for f in islice(schema, ROWS)],
                  "truncated": len(schema) > ROWS, "note": f"Parquet 表 · {file.metadata.num_rows:,} 行，{len(schema):,} 列。"}
        fields = [f.name for f in islice(schema, 24) if pa.types.is_primitive(f.type) or
                  pa.types.is_string(f.type) or pa.types.is_large_string(f.type)]
        if not fields or not file.num_row_groups or file.metadata.row_group(0).total_byte_size > 8 * 1024 * 1024:
            return result
        batch = next(file.iter_batches(batch_size=ROWS, row_groups=[0], columns=fields, use_threads=False), None)
        if batch is not None and batch.num_rows:
            def display(value):
                text = "" if value is None else str(value)
                return text if len(text) <= 160 else text[:160] + "…"
            result["sample"] = {"columns": fields, "rows": [
                [display(col[i].as_py()) for col in batch.columns] for i in range(batch.num_rows)]}
        return result


def archive_preview(path):
    with path.open("rb") as stream:
        # Check the directory size before ZipFile materializes it in memory (including ZIP64).
        end = zipfile._EndRecData(stream)
        if not end:
            raise ValueError("无法读取 ZIP 目录。")
        if end[zipfile._ECD_SIZE] > 16 * 1024 * 1024 or end[zipfile._ECD_ENTRIES_TOTAL] > 50_000:
            raise ValueError("归档目录过大，请下载后浏览。")
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            return {"columns": ["归档路径", "原始大小（字节）"],
                    "rows": [[x.filename, x.file_size] for x in entries[:ROWS]], "truncated": len(entries) > ROWS,
                    "note": f"ZIP 目录 · 共 {len(entries):,} 项。"}


def preview_file(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("请选择文件。")
    ext = path.suffix.lower()
    if ext in {".h5", ".hdf5", ".h5ad"}:
        return hdf_preview(path)
    if ext == ".zip":
        return archive_preview(path)
    if ext == ".parquet":
        return parquet_preview(path)
    gz = ext == ".gz"
    name = Path(path.stem) if gz else path
    ext = name.suffix.lower()
    if ext not in TEXT | {".csv", ".tsv", ".tab"}:
        raise ValueError("当前格式可下载原文件查看。")
    with (gzip.open(path, "rb") if gz else path.open("rb")) as f:
        raw = f.read(LIMIT + 1)
    clipped = len(raw) > LIMIT
    prefix = raw[:LIMIT]
    encodings = ("utf-16",) if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            data = codecs.getincrementaldecoder(encoding)().decode(prefix, final=not clipped)
            break
        except UnicodeError:
            continue
    else:
        data = prefix.decode("utf-8-sig", errors="replace")
    if ext in {".csv", ".tsv", ".tab"}:
        reader = csv.reader(io.StringIO(data), delimiter="," if ext == ".csv" else "\t")
        first = next(reader, [])
        mex = {"barcodes": ["条码"], "features": ["特征 ID", "特征名称", "特征类型"], "genes": ["基因 ID", "基因名称"]}
        labels = mex.get(name.stem.lower()) if ext == ".tsv" else None
        if name.name.lower() == "sj.out.tab":
            labels = ["染色体", "内含子起点", "内含子终点", "链", "剪接基序", "已有注释", "唯一比对读段", "多重比对读段", "最大悬垂长度"]
        if labels and first:
            headers = [(labels[i] if i < len(labels) else f"字段 {i+1}") for i in range(len(first))]
            rows = [first] + list(islice(reader, ROWS))
        else:
            headers = first
            rows = list(islice(reader, ROWS + 1))
        return {"columns": headers, "rows": rows[:ROWS], "truncated": clipped or len(rows) > ROWS}
    if ext == ".json" and not clipped:
        try:
            data = json.dumps(json.loads(data), ensure_ascii=False, indent=2)
        except (ValueError, RecursionError):
            pass
    return {"text": data, "truncated": clipped}

