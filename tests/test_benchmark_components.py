import tempfile
import unittest
from pathlib import Path
import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from backend.analysis import _quality_data, preview_qc
from backend.annotation import annotate_clusters, matching_panel, marker_detection, panel_support
from backend.component_jobs import input_slots
from backend.capture_inputs import split_file
from backend.qc import parameters, read_counts
from backend.workspace import normalize_spec

class CaptureAndAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self,name,values,genes,**obs):
        obj=ad.AnnData(sparse.csr_matrix(values),var=pd.DataFrame(index=genes),
                       obs=pd.DataFrame(obs,index=[f"b{i}" for i in range(len(values))]))
        path=self.root/(name+".h5ad")
        obj.write_h5ad(path)
        return path

    def test_repeated_matrix_and_distinct_fastq_prefix(self):
        path=self.write("a",[[1,1,1]],list("abc"))
        libs=[{"id":name,"path":str(path)} for name in ("one","two")]
        with self.assertRaisesRegex(ValueError,"重复"):
            preview_qc({"libraries":libs})
        with self.assertRaisesRegex(ValueError,"重复"):
            normalize_spec({"libraries":libs})
        fastq=[dict(lib,path=str(self.root),kind="fastq",prefix=lib["id"]) for lib in libs]
        self.assertEqual(len(normalize_spec({"libraries":fastq})["libraries"]),2)

    def test_declared_multicapture_is_not_pooled(self):
        path=self.write("combined",[[1],[2]],["g"],capture=["A","B"])
        with self.assertRaisesRegex(ValueError,"多个物理捕获"):
            read_counts(path)
        libs=split_file(path,self.root/"split")
        self.assertEqual([r["id"] for r in libs],["A","B"])
        self.assertEqual([r["batch"] for r in libs],["unspecified","unspecified"])
        self.assertEqual([read_counts(r["path"]).X.sum() for r in libs],[1,2])

    def test_split_does_not_flatten_multiplexed_condition(self):
        path=self.write("mux",[[1],[2]],["g"],capture=["A","A"],condition=["treated","control"])
        with self.assertRaisesRegex(ValueError,"混样"):
            split_file(path,self.root/"split")
        self.assertFalse((self.root/"split").exists())

    def test_final_local_qc_matches_shared_gene_filter(self):
        a=self.write("a",[[0,0,0,4],[1,2,1,0]],list("abcx"))
        b=self.write("b",[[1,1,1]],list("abc"))
        libs=[{"id":name,"path":str(path)} for name,path in [("A",a),("B",b)]]
        cfg=parameters({"feature_join":"intersection","doublet_mode":"off","mad_multiplier":0})
        _,global_qc,*_=_quality_data({"libraries":libs},cfg,{},self.root,lambda *args:None)
        local=pd.read_csv(self.root/"captures"/"001"/"qc.tsv",sep="\t",index_col=0)
        self.assertFalse(local.at["A:b0","retained"])
        self.assertEqual(local.at["A:b0","filter_reason"],global_qc.at["A:b0","filter_reason"])

    def test_representation_can_select_native_pca_with_harmony_present(self):
        keys={"obsm/X_pca","obsm/X_pca_harmony"}
        self.assertEqual(input_slots("graph",keys,{"graph_representation":"X_pca"})["representation"],"obsm/X_pca")
        self.assertEqual(input_slots("graph",keys,{})["representation"],"obsm/X_pca_harmony")

    def test_missing_condition_keeps_native_representation(self):
        from backend.advanced import build_representation
        obj=ad.AnnData(np.random.default_rng(3).normal(size=(120,8)).astype(np.float32))
        obj.obs["batch"]=["a"]*60+["b"]*60
        obj.obs["condition"]="unspecified"
        obj.var["highly_variable"]=True
        rep,_,diagnosis=build_representation(obj,parameters({"integration":"harmony"}),self.root,
                                            obj.var.highly_variable.to_numpy(),[])
        self.assertEqual((rep,diagnosis["status"]),("X_pca","ineligible"))

    def test_scoped_annotation_and_absent_support(self):
        panel=matching_panel("Arabidopsis thaliana","root","scRNA","TAIR10")
        self.assertIsNone(matching_panel("Arabidopsis thaliana","root","snRNA","TAIR10"))
        genes=panel["types"]["trichoblast"]["positive"]
        obj=ad.AnnData(sparse.csr_matrix(np.vstack([np.ones((12,len(genes))),np.zeros((12,len(genes)))])),
                       var=pd.DataFrame(index=genes))
        obj.layers["counts"]=obj.X.copy()
        obj.obs["leiden"]=["a"]*12+["b"]*12
        labels,ev=annotate_clusters(obj,panel)
        self.assertEqual(labels.iloc[0],"trichoblast")
        self.assertEqual(labels.iloc[-1],"unknown")
        self.assertTrue(ev["source"].notna().all())
        self.assertTrue(annotate_clusters(obj,None)[0].eq("unknown").all())
        obj.obs["leiden"]="one"
        labels,ev=annotate_clusters(obj,panel)
        self.assertTrue(labels.eq("unknown").all())
        self.assertEqual(set(ev.rejection),{"no_comparison_cells"})

    def test_panel_support_distinguishes_missing_silent_and_expressed_genes(self):
        panel = {"types": {"target": {"positive": ["g1", "g2", "absent"]}}}
        obj = ad.AnnData(sparse.csr_matrix([[0,0], [1,0]]), var=pd.DataFrame(index=["g1","g2"]))
        obj.layers["counts"] = obj.X.copy()
        obj.obs["leiden"] = ["first", "last"]
        detection = marker_detection(obj, panel)
        info = panel_support(detection, panel, "specificity").iloc[0]
        self.assertEqual((info.positive_measured, info.positive_detected, info.missing_ids, info.silent_ids),
                         (2, 1, "absent", "g2"))
        self.assertTrue(info.axis_sufficient)
        self.assertFalse(info.detection_sufficient)
        self.assertTrue(panel_support(detection, panel, "prevalence").iloc[0].detection_sufficient)
        self.assertTrue(panel_support(detection, None, "specificity").empty)

if __name__=="__main__":
    unittest.main()

