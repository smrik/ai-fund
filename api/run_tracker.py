import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from src.utils import utc_now_iso

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="alpha-pod-api")
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_LOCK = threading.Lock()

def initialize_run(kind: str, *, ticker: str | None = None, metadata: dict[str, Any] | None = None) -> str:
    run_id = uuid4().hex
    with _RUN_LOCK:
        _RUNS[run_id] = {
            "run_id": run_id,
            "kind": kind,
            "ticker": ticker,
            "status": "queued",
            "progress": 0.0,
            "message": None,
            "result": None,
            "error": None,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "metadata": metadata or {},
        }
    return run_id

def update_run(run_id: str, **updates: Any) -> dict[str, Any]:
    with _RUN_LOCK:
        run = _RUNS[run_id]
        run.update(updates)
        run["updated_at"] = utc_now_iso()
        return dict(run)

def get_run(run_id: str) -> dict[str, Any] | None:
    with _RUN_LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return None
        return dict(run)

def submit_background_run(
    kind: str,
    runner: Callable[[str], Any],
    *,
    ticker: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    run_id = initialize_run(kind, ticker=ticker, metadata=metadata)

    def _wrapped() -> None:
        update_run(run_id, status="running", progress=0.0)
        try:
            result = runner(run_id)
            update_run(run_id, status="completed", progress=1.0, result=jsonable_encoder(result), error=None)
        except Exception as exc:  # pragma: no cover - defensive guard
            update_run(run_id, status="failed", error=str(exc), message=str(exc))

    _EXECUTOR.submit(_wrapped)
    return run_id
