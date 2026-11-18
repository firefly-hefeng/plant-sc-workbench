"""Offline, assembly-specific organelle gene sets. IDs are matched literally."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "resources"
GROUPS = ("mitochondrial", "plastid")
ALIASES = {"mitochondria": "mitochondrial", "chloroplast": "plastid",
           "pt": "plastid", "mt": "mitochondrial", **{g: g for g in GROUPS}}


def list_references():
    return json.loads((ROOT / "references.json").read_text(encoding="utf-8"))


def _normalise(pairs):
    sets = {name: set() for name in GROUPS}
    for ident, group in pairs:
        group = ALIASES.get(str(group).strip().lower())
        if not isinstance(ident, str) or not ident.strip() or not group:
            raise ValueError("参考集每行应包含稳定 gene_id 和 mitochondrial 或 plastid。")
        sets[group].add(ident.strip())
    if sets["mitochondrial"] & sets["plastid"]:
        raise ValueError("参考集中同一基因同时属于两类细胞器。")
    if not any(sets.values()):
        raise ValueError("参考集缺少有效基因。")
    return {name: sorted(ids) for name, ids in sets.items()}


def _read_table(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), delimiter="\t")
    if not {"gene_id", "compartment"}.issubset(reader.fieldnames or []):
        raise ValueError("参考 TSV 需要 gene_id 和 compartment 表头。")
    return _normalise((row["gene_id"], row["compartment"]) for row in reader)


def resolve_reference(reference_id=None, custom_path=None):
    if custom_path:
        path = Path(custom_path).resolve(strict=True)
        data = path.read_bytes()
        if path.suffix.lower() == ".json":
            obj = json.loads(data.decode("utf-8-sig"))
            sets = obj.get("sets", obj)
            pairs = []
            for group, ids in sets.items():
                if group in ALIASES:
                    if not isinstance(ids, list):
                        raise ValueError("参考 JSON 分组应为基因 ID 数组。")
                    pairs.extend((gene, group) for gene in ids)
            genes = _normalise(pairs)
        else:
            genes = _read_table(data)
        meta = {"id": "custom", "label": path.name, "species": "", "assembly": "",
                "path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    elif reference_id in (None, "", "none", "auto"):
        genes = {group: [] for group in GROUPS}
        meta = {"id": "none", "label": "未指定参考", "species": "", "assembly": ""}
    else:
        meta = next((row for row in list_references() if row["id"] == reference_id), None)
        if meta is None:
            raise ValueError(f"无法识别的参考版本：{reference_id}")
        data = (ROOT / meta["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError("内置参考文件 SHA-256 校验失败。")
        genes = _read_table(data)
    return {**meta, **genes, "mitochondria": genes["mitochondrial"], "chloroplast": genes["plastid"],
            "sets": genes, "counts": {g: len(genes[g]) for g in GROUPS}}


def reference_overlap(reference, gene_ids):
    """Report measurable coverage for each compartment on the matrix gene axis."""
    ids = set(gene_ids)
    return {g: {"matched": len(ids.intersection(reference[g])), "catalog": len(reference[g])}
            for g in GROUPS}
