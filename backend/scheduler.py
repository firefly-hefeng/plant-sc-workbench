"""Bounded first-in-first-out dispatch for a single local compute service."""
from collections import deque
from contextlib import contextmanager
import os
import threading


class JobQueue:
    def __init__(self, capacity, execute):
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise ValueError("并发作业数必须是 1 至 32 的整数")
        self.capacity = capacity
        self.execute = execute
        self.lock = threading.RLock()
        self.waiting = deque()
        self.active = set()
        self.closed = False

    def submit(self, job, base):
        with self.lock:
            if self.closed:
                raise RuntimeError("计算服务正在关闭")
            self.waiting.append((job, base))
            self._dispatch()

    def remove(self, job):
        with self.lock:
            self.waiting = deque(item for item in self.waiting if item[0] != job)

    def _dispatch(self):
        while self.waiting and len(self.active) < self.capacity and not self.closed:
            job, base = self.waiting.popleft()
            self.active.add(job)
            threading.Thread(target=self._run, args=(job,base), daemon=True).start()

    def _run(self, job, base):
        try:
            self.execute(job,base)
        finally:
            with self.lock:
                self.active.discard(job)
                self._dispatch()

    def status(self):
        with self.lock:
            return dict(limit=self.capacity, active=len(self.active), waiting=len(self.waiting))

    def stop(self):
        with self.lock:
            self.closed = True
            return [job for job,_ in self.waiting] + list(self.active)


@contextmanager
def registry_owner(home):
    """A second server must never mark another server's live jobs interrupted."""
    from pathlib import Path
    root=Path(home).resolve()
    root.mkdir(parents=True,exist_ok=True)
    with (root/".service.lock").open("a+b") as lock:
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有服务正在管理此工作目录") from exc
        yield

