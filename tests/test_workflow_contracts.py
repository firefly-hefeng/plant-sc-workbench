"""Interface invariants shared by the no-code frontend and MCP client."""
import gzip
from pathlib import Path
import sys,tempfile,unittest
import anndata as ad
import pandas as pd
from scipy import sparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import upstream
from backend.blocks import recipe
from backend.catalog import discover
from backend.inspection import feature_ids
from backend.workspace import normalize_spec,child

class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_starsolo_raw_filtered_pairs(self):
        for kind in ("raw","filtered"):
            path=self.root/"capture"/"Solo.out"/"GeneFull"/kind
            path.mkdir(parents=True);(path/"matrix.mtx").touch()
        lib,=discover(self.root/"capture")
        self.assertEqual(lib["kind"],"raw")
        self.assertEqual(Path(lib["filtered_path"]).name,"filtered")
        self.assertEqual(lib["id"],"capture")
    def test_counts_id_axis_and_gex(self):
        f=self.root/"data.h5ad"
        var=pd.DataFrame({"gene_ids":pd.Categorical(["ATMG00010","ATCG00010"])},index=["mtA","cpA"])
        ad.AnnData(sparse.csr_matrix([[1,2]]),var=var).write_h5ad(f)
        self.assertEqual(feature_ids(f),set(var.gene_ids))
        (self.root/"features.tsv").write_text("ATMG00010\tmtA\tGene Expression\nnoise\tab\tAntibody Capture\n")
        self.assertEqual(feature_ids(self.root),{"ATMG00010"})
    def test_mixed_capture_soupx_requires_each_background(self):
        for name in ("a-raw","a-filtered","b-filtered"):
            (self.root/name).mkdir()
        libs=[dict(id="a",path=str(self.root/"a-raw"),kind="raw",filtered_path=str(self.root/"a-filtered")),
              dict(id="b",path=str(self.root/"b-filtered"),kind="matrix")]
        spec=normalize_spec(dict(libraries=libs,params=dict(ambient_mode="soupx")))
        plan=recipe(spec,{"soupx":{"available":True}})
        row=next(r for r in plan["blocks"] if r["id"]=="ambient")
        self.assertEqual(row["state"],"blocked");self.assertIn("b","".join(row["issues"]))
    def test_raw_only_schedules_calls(self):
        spec=normalize_spec({"libraries":[dict(id="a",path=str(self.root),kind="raw")]})
        plan=recipe(spec,{"emptydrops":{"available":True}})
        self.assertTrue(plan["ready"])
        self.assertLess([r["id"] for r in plan["blocks"]].index("call"),[r["id"] for r in plan["blocks"]].index("qc"))
    def test_truncated_v3_requires_explicit_layout(self):
        for i,n in enumerate((26,98),1):
            p=self.root/f"Sample_S1_L001_R{i}_001.fastq.gz"
            with gzip.open(p,"wt") as f:f.write(f"@pair/{i}\n"+("A"*n)+"\n+\n"+("I"*n)+"\n")
        with self.assertRaises(ValueError):upstream.plan_fastq(self.root,"Sample",None)
        self.assertEqual(upstream.plan_fastq(self.root,"Sample",None,chemistry="SC3Pv3_10")["pairs"],1)
    def test_file_browser_scope(self):
        self.assertEqual(child(self.root,"data"),self.root/"data")
        with self.assertRaises(ValueError):child(self.root,"../outside")
if __name__=="__main__":unittest.main()

