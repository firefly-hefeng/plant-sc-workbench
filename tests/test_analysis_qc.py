"""Regression checks for the stable feature axis, native QC and scoped filtering."""
from pathlib import Path
import sys
import tempfile
import unittest

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.io import mmwrite

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.analysis import _capture, _merge, preview_qc
from backend.qc import parameters, read_counts


class QualityControlTests(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory()
        self.root=Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def matrix(self, name, values, genes=None):
        genes=genes or ["cp","mt","gene"]
        obs=pd.DataFrame(index=["b"+str(i) for i in range(len(values))])
        var=pd.DataFrame(index=genes)
        path=self.root/(name+".h5ad")
        ad.AnnData(sparse.csr_matrix(np.asarray(values)),obs=obs,var=var).write_h5ad(path)
        return path

    def test_noncounts(self):
        path=self.matrix("fractional",[[1.,.4,1.]])
        with self.assertRaisesRegex(ValueError,"整数"):
            read_counts(path)

    def test_reference_unavailable_is_missing(self):
        path=self.matrix("counts",[[1,2,3],[2,3,4]])
        spec={"libraries":[{"id":"A","path":str(path)}],"params":{"max_mito_pct":20},"reference":{"sets":{}}}
        with self.assertRaisesRegex(ValueError,"参考基因"):
            preview_qc(spec)

    def test_qc_rule_overlap_and_scope(self):
        path=self.matrix("counts",[[2,2,0],[0,0,0],[0,0,10]])
        lib={"id":"L","path":str(path)}
        obj,rec,_=_capture(lib,{"sets":{"mitochondria":["mt"],"plastid":["cp"]}},
                          parameters({"max_mito_pct":40,"max_plastid_pct":40}),predict=False)
        self.assertEqual(rec["retained_cells"],1)
        self.assertEqual(rec["multiple_rules"],2)
        self.assertEqual(obj.obs.at["L:b0","mito_pct"],50)
        self.assertIn("high_plastid",obj.obs.at["L:b0","filter_reason"])
        self.assertTrue(np.isnan(obj.obs.at["L:b1","plastid_pct"]))

    def test_mismatched_axes_and_native_qc(self):
        x=self.matrix("x",[[20,1,1,10],[0,0,0,3]],["g1","g2","g3","extra"])
        y=self.matrix("y",[[4,2,1]],["g3","g1","g2"])
        cfg=parameters({"feature_join":"intersection"})
        records=[_capture({"id":name,"path":str(path)},{},cfg,predict=False) for name,path in (("a",x),("b",y))]
        objs=[o for o,r,n in records];meta=[r for o,r,n in records]
        with self.assertRaisesRegex(ValueError,"基因集合不同"):
            _merge(objs,meta,parameters({}))
        merged,qc=_merge(objs,meta,cfg)
        self.assertEqual(merged.shape,(2,3))
        self.assertEqual(qc.loc["a:b1","filter_reason"],"no_counts_on_shared_features")
        self.assertEqual(qc.loc["a:b0","total_counts"],32)
        self.assertEqual(qc.loc["a:b0","feature_join_removed_counts"],10)

    def test_mex_excludes_antibodies(self):
        folder=self.root/"matrix"
        folder.mkdir()
        (folder/"features.tsv").write_text("g\tGene\tGene Expression\nab\tAB1\tAntibody Capture\n",encoding="utf-8")
        (folder/"barcodes.tsv").write_text("cell\n",encoding="utf-8")
        mmwrite(folder/"matrix.mtx",sparse.coo_matrix([[2],[5]]))
        obj=read_counts(folder)
        self.assertEqual(obj.shape,(1,1))
        self.assertEqual(obj.X.sum(),2)

    def test_raw_liquids_do_not_reach_qc(self):
        with self.assertRaisesRegex(ValueError,"有效条码"):
            preview_qc({"libraries":[{"id":"x","kind":"raw","path":"unused"}]})


if __name__=="__main__":
    unittest.main()
