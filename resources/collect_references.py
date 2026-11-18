"""Rebuild the small, versioned organelle ID resources from Ensembl Plants."""
import csv
import gzip
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from urllib.parse import unquote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
PACKS = [
    ("ath-tair10-62", "拟南芥 Col-0", "Arabidopsis_thaliana", "TAIR10", 62),
    ("osa-irgsp1-62", "水稻 Nipponbare", "Oryza_sativa", "IRGSP-1.0", 62),
    ("zma-b73v4-48", "玉米 B73 v4", "Zea_mays", "B73_RefGen_v4", 48),
]
TERMS = "https://www.ensembl.org/about/articles/ensembl-content-disclaimer"


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def collect(pack):
    key, label, species, assembly, release = pack
    base = f"https://ftp.ensemblgenomes.ebi.ac.uk/pub/plants/release-{release}/gff3/{species.lower()}/"
    folder = ROOT / "organelles" / key
    folder.mkdir(parents=True, exist_ok=True)
    sources = []
    rows = {}
    for seq, group in [("Mt", "mitochondrial"), ("Pt", "plastid")]:
        name = f"{species}.{assembly}.{release}.chromosome.{seq}.gff3.gz"
        url = base + name
        with urlopen(url, timeout=45) as stream:
            data = stream.read()
        (folder / name).write_bytes(data)
        source_genes = set()
        for line in gzip.decompress(data).decode("utf-8").splitlines():
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) != 9 or cols[0] != seq:
                continue
            attrs = dict(item.split("=", 1) for item in cols[8].split(";") if "=" in item)
            if not attrs.get("ID", "").startswith("gene:"):
                continue
            gene_id = unquote(attrs["gene_id"])
            source_genes.add(gene_id)
            rows.setdefault(gene_id, set()).add(group)
        if not source_genes:
            raise ValueError(f"No gene IDs in {url}")
        sources.append(dict(url=url, file=name, bytes=len(data), sha256=fingerprint(data),
                            contig=seq, source_gene_count=len(source_genes)))
    ambiguous = sorted(gene for gene, groups in rows.items() if len(groups) != 1)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerow(["gene_id", "compartment"])
    for gene_id in sorted(set(rows) - set(ambiguous)):
        writer.writerow([gene_id, next(iter(rows[gene_id]))])
    table = buf.getvalue().encode("utf-8")
    (folder / "genes.tsv").write_bytes(table)
    return dict(id=key, label=label, species=species.replace("_"," "), assembly=assembly,
                release=f"Ensembl Plants {release}", source_url=base, sources=sources,
                term_url=TERMS, retrieved=str(date.today()),
                counts={g: sum(gs == {g} for gs in rows.values()) for g in ("mitochondrial", "plastid")},
                excluded_ambiguous_ids=ambiguous, file=f"organelles/{key}/genes.tsv", sha256=fingerprint(table))


if __name__ == "__main__":
    manifest = [collect(pack) for pack in PACKS]
    (ROOT / "references.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n", encoding="utf-8")
