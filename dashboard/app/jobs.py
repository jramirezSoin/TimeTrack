"""Tareas largas en segundo plano con un registro de progreso que la UI consulta."""
from __future__ import annotations

import threading
import uuid
from typing import Any, Callable


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "running"  # running | done | error
        self.lines: list[str] = []
        self.result: Any = None
        self.error: str | None = None
        self._lock = threading.Lock()

    def emit(self, line: str) -> None:
        with self._lock:
            self.lines.append(str(line))

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.lines)


class JobStore:
    def __init__(self, max_jobs: int = 50):
        self._jobs: dict[str, Job] = {}
        self._max = max_jobs
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(kind)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > self._max:  # descarta los más viejos
                self._jobs.pop(next(iter(self._jobs)))

        def run():
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as e:  # el mensaje se muestra en la UI
                job.error = str(e) or e.__class__.__name__
                job.status = "error"

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)
