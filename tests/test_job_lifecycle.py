"""Exercise cancellation and interrupted-job recovery in an isolated registry."""
from pathlib import Path
import tempfile
import time
import unittest
from backend.workspace import Workspace,ROOT,timestamp

class LifecycleTests(unittest.TestCase):
    def test_cancel_returns_terminal_state(self):
        with tempfile.TemporaryDirectory() as root:
            store=Workspace(root);p=store.create_project("cancel test")
            example=ROOT/"examples"/"GSM5320262.h5ad"
            spec=dict(project=p["id"],libraries=[dict(id="one",path=str(example))])
            job=store.submit(spec)
            self.assertEqual(store.cancel(job["id"])["state"],"cancelled")
            end=time.monotonic()+12
            while job["id"] in store.processes and time.monotonic()<end:time.sleep(.05)
            self.assertEqual(store.job(job["id"])["state"],"cancelled")
            self.assertFalse((Path(p["path"])/job["output"]/"receipt.json").exists())
    def test_startup_marks_only_pending_or_running_interrupted(self):
        with tempfile.TemporaryDirectory() as root:
            store=Workspace(root);p=store.create_project("restore test")
            with store.connect() as db:
                for state in ("queued","running","succeeded"):
                    db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",(state,p["id"],state,"",timestamp(),None,"analysis","unused"))
            reopened=Workspace(root)
            self.assertEqual(reopened.job("running")["state"],"interrupted")
            self.assertEqual(reopened.job("queued")["state"],"interrupted")
            self.assertEqual(reopened.job("succeeded")["state"],"succeeded")
if __name__=="__main__":unittest.main()

