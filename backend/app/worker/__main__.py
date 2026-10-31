"""worker 进程入口：`python -m app.worker`。"""

from __future__ import annotations

from arq.worker import run_worker

from app.worker.worker import WorkerSettings

if __name__ == "__main__":
    run_worker(WorkerSettings)
