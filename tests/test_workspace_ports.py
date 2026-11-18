import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from backend.blocks import BLOCKS
from backend.ports import module_definition, TASKS, contract
from backend.project_views import copy_file, make_dir
from backend.scheduler import JobQueue, registry_owner
from backend.workspace import child, normalize_spec
from backend.worker import input_identities
from backend.blocks import recipe


class WorkspacePortsTests(unittest.TestCase):
    def test_catalog_has_typed_ports_and_method_source(self):
        self.assertEqual(len(BLOCKS),13)
        for block in BLOCKS:
            definition=module_definition(block.id)
            self.assertTrue(definition["practice"]["source"].startswith("https://"))
            for side in ("inputs","outputs"):
                for port in definition["ports"][side]:
                    self.assertTrue(port["type"] and port["id"] and port["label"])
                    self.assertIsInstance(port["required"],bool)
        for task in TASKS:
            self.assertTrue(all(contract(task,True)[k] for k in ("inputs","outputs")))

    def test_reference_and_negative_input_routing(self):
        with tempfile.TemporaryDirectory() as d:
            lib=dict(id="plant",kind="filtered",path=d)
            spec=normalize_spec(dict(libraries=[lib],params={"cell_calling":"emptydrops"}))
            self.assertFalse(recipe(spec,{"emptydrops":{"available":True}})["ready"])
            spec["libraries"][0]["raw_path"]=d
            self.assertTrue(recipe(spec,{"emptydrops":{"available":True}})["ready"])

    def test_copy_no_overwrite_and_protected_directories(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            (root/"runs").mkdir()
            (root/"source").write_text("abc")
            store=SimpleNamespace(project=lambda pid:{"path":d},locate=lambda q:(root,child(root,q["path"])))
            spec=dict(project="p",directory="",name="notes")
            make_dir(store,spec)
            args=dict(project="p",directory="notes",path="source",name="file")
            copy_file(store,args)
            with self.assertRaises(FileExistsError):
                copy_file(store,args)
            self.assertEqual((root/"notes/file").read_text(),"abc")
            for dest in ("runs",".."):
                with self.assertRaises(ValueError):
                    copy_file(store,{**args,"directory":dest})
            with self.assertRaises(ValueError):
                make_dir(store,{**spec,"scope":"input"})

    def test_fifo_waiting_cancel_and_lock(self):
        started, release, finished=Event(),Event(),Event()
        order=[]
        def run(job,base):
            order.append(job)
            if job=="first":
                started.set();release.wait(5)
            if job=="last":
                finished.set()
        q=JobQueue(1,run)
        q.submit("first","");self.assertTrue(started.wait(5))
        q.submit("removed","");q.submit("last","")
        self.assertEqual(q.status(),dict(limit=1,waiting=2,active=1))
        q.remove("removed");release.set()
        self.assertTrue(finished.wait(5));self.assertEqual(order,["first","last"])
        with tempfile.TemporaryDirectory() as d:
            with registry_owner(d):
                with self.assertRaises(RuntimeError):
                    with registry_owner(d):pass
            with registry_owner(d):pass

    def test_umap_kernel_cannot_mutate_the_input_graph(self):
        from unittest.mock import patch
        from scipy.sparse import csr_matrix
        import numpy as np
        from backend.advanced import embed_graph
        graph=csr_matrix([[0,.000001],[.000001,0]])
        obj=SimpleNamespace(uns={"neighbors":{}},obsp={"connectivities":graph},obsm={"X_umap":np.zeros((2,2))})
        def consume(adata, **kwargs):
            adata.obsp["connectivities"].data[:]=0
        with patch("scanpy.tl.umap",side_effect=consume):
            embed_graph(obj,{"seed":0,"min_dist":.5})
        self.assertIs(obj.obsp["connectivities"],graph)
        self.assertTrue((graph.data==.000001).all())

    def test_identity_ignores_unrelated_files_and_deduplicates_roles(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for f in ("matrix.mtx","features.tsv","barcodes.tsv","unrelated.fastq.gz"):
                (root/f).write_text("fixture")
            spec=normalize_spec(dict(libraries=[dict(path=d,id="one",kind="raw",raw_path=d)]))
            inputs=input_identities(spec)
            self.assertEqual({Path(x["path"]).name for x in inputs},{"matrix.mtx","features.tsv","barcodes.tsv"})
            self.assertEqual(len(inputs),3)


if __name__=="__main__":unittest.main()

