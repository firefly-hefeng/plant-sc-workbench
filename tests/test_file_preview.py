import gzip
from pathlib import Path
import tempfile
import unittest
import zipfile
from urllib.parse import urljoin
from urllib.request import urlopen

import h5py
import pyarrow as pa
import pyarrow.parquet as pq
from backend.file_preview import LIMIT, preview_file
from backend.native_reports import report_service


class FilePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_gzip_mex_retains_first_barcode_and_caps_rows(self):
        p = self.root / "barcodes.tsv.gz"
        with gzip.open(p, "wt", encoding="utf-8") as f:
            f.writelines(f"BC{i}\n" for i in range(102))
        view = preview_file(p)
        self.assertEqual((view["columns"], view["rows"][0], len(view["rows"])), (["条码"], ["BC0"], 100))
        self.assertTrue(view["truncated"])

    def test_long_fastq_and_quoted_csv(self):
        p = self.root / "reads.fastq.gz"
        with gzip.open(p, "wb") as f:
            f.write(b"@read\nAC\n+\n!!\n" * 11000)
        self.assertEqual(len(preview_file(p)["text"]), LIMIT)
        p = self.root / "counts.csv"
        p.write_text('样本,UMI\n"一,二",12\n', encoding="utf-8-sig")
        self.assertEqual(preview_file(p)["rows"], [["一,二", "12"]])

    def test_count_matrices_have_explicit_axes(self):
        p = self.root / "sparse.h5ad"
        with h5py.File(p, "w") as f:
            x = f.create_group("X")
            x.attrs["shape"] = [83210, 20513]
            f["layers"] = h5py.ExternalLink("unavailable.h5", "/layers")
        rows = dict(preview_file(p)["rows"])
        self.assertIn("83,210 个细胞", rows["表达矩阵 X"])
        self.assertEqual(rows["/layers"], "链接")
        p = self.root / "tenx.h5"
        with h5py.File(p, "w") as f:
            f.create_dataset("matrix/shape", data=[20513, 83210])
        self.assertIn("20,513 个特征 × 83,210 个条码", dict(preview_file(p)["rows"])["10x 计数矩阵"])

    def test_archives_and_parquet_schema(self):
        p = self.root / "附件.zip"
        with zipfile.ZipFile(p, "w") as f:
            f.writestr("目录/清单.tsv", "a\tb")
        self.assertEqual(preview_file(p)["rows"], [["目录/清单.tsv", 3]])
        p = self.root / "qc.parquet"
        pq.write_table(pa.table({"UMI": [2, 3]}), p)
        self.assertIn("2 行，1 列", preview_file(p)["note"])
        self.assertEqual(preview_file(p)["rows"], [["UMI", "int64"]])
        self.assertEqual(preview_file(p)["sample"]["rows"], [["2"], ["3"]])

    def test_report_origin_and_bundled_assets(self):
        doc = self.root / "简 报.html"
        doc.write_text('<script src="assets/plot.js"></script>', encoding="utf-8")
        (self.root / "assets").mkdir()
        asset = self.root / "assets/plot.js"
        asset.write_text("document.title='QC'", encoding="utf-8")
        with report_service(8876) as server:
            url = server.document(doc)["url"]
            with urlopen(url) as response:
                self.assertNotEqual(server.server_port, 8876)
                self.assertIn("frame-ancestors", response.headers["Content-Security-Policy"])
                self.assertEqual(response.read(), doc.read_bytes())
            with urlopen(urljoin(url, "assets/plot.js")) as response:
                self.assertEqual(response.read(), asset.read_bytes())
            with self.assertRaises(ValueError):
                server.document(asset)

