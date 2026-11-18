"""Stage input acceptance and all-or-nothing publication."""
import io
import json
import tempfile
import unittest
from pathlib import Path
import h5py
from backend.stage_inputs import describe, receive
from backend.workspace import Workspace

def packet(files):
    manifest=json.dumps({"files":[{"name":name,"size":len(data)} for name,data in files]}).encode()
    return len(manifest).to_bytes(4,"big")+manifest+b"".join(data for _,data in files)

class StageInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Workspace(self.root)
        self.project=self.store.create_project("test")
        self.uploads=Path(self.project["path"])/"imports"

    def upload(self,data,role="counts",**kwargs):
        return receive(self.store,{"project":self.project["id"],"role":role,**kwargs},io.BytesIO(data),len(data))

    def test_mex_sample_sheet_paths_survive_publication(self):
        data=packet([("trial/samples.csv",b"id,path,sample\nroot,F1,plant-A\n"),
                     ("trial/F1/barcodes.tsv",b"C1\n"),("trial/F1/features.tsv",b"AT1\n"),
                     ("trial/F1/matrix.mtx",b"%%MatrixMarket matrix coordinate integer general\n1 1 1\n1 1 2\n")])
        res=self.upload(data)
        lib=res["libraries"][0]
        self.assertEqual((lib["id"],lib["sample"]),("root","plant-A"))
        self.assertTrue((Path(lib["path"])/"matrix.mtx").is_file())

    def test_incomplete_batch_removed(self):
        data=packet([("features.tsv",b"AT1\n")])
        with self.assertRaisesRegex(ValueError,"上传中断"):
            receive(self.store,{"project":self.project["id"],"role":"counts"},io.BytesIO(data[:-2]),len(data))
        self.assertEqual(list(self.uploads.iterdir()),[])
        with self.assertRaisesRegex(ValueError,"缺少"):
            self.upload(packet([("matrix.mtx",b"test")]))
        self.assertEqual(list(self.uploads.iterdir()),[])

    def test_duplicate_or_invalid_file_name(self):
        for files in ([("gene.tsv",b"1"),("Gene.tsv",b"2")],[("../gene.tsv",b"1")]):
            with self.assertRaises(ValueError):self.upload(packet(files))
        self.assertFalse(self.uploads.exists())

    def test_reads_need_both_mates_per_lane(self):
        q=packet([("R_S1_L001_R1_001.fastq.gz",b"1")])
        with self.assertRaisesRegex(ValueError,"R1/R2"):self.upload(q,"reads")
        self.assertEqual(list(self.uploads.iterdir()),[])

    def test_module_specific_fields(self):
        path=self.root/"plain.h5ad"
        with h5py.File(path,"w") as h:
            for name in ("obs","var","obsp/connectivities"):h.create_group(name)
        graph=describe(path,"object","leiden")
        self.assertEqual(graph["slots"]["graph"],"obsp/connectivities")
        for module in ("features","pca","graph","umap"):
            with self.assertRaisesRegex(ValueError,"缺少"):describe(path,"object",module)

