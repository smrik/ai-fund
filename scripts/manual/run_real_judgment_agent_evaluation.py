from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_PROFILES = ("comps_analysis", "valuation_review", "analyst_prep_synthesis")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _load_latest_packet(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    profile_name: str,
) -> dict[str, Any] | None:
    from db.loader import load_evidence_packet

    row = conn.execute(
        """
        SELECT id
        FROM evidence_packets
        WHERE ticker = ? AND profile_name = ?
        ORDER BY generated_at DESC, id DESC
        LIMIT 1
        """,
        [ticker, profile_name],
    ).fetchone()
    if row is None:
        return None
    return load_evidence_packet(conn, int(row["id"]))


def _evaluate_profile(packet_payload: dict[str, Any], profile_name: str) -> dict[str, Any]:
    from src.contracts.evidence_packet import EvidencePacket
    from src.stage_03_judgment.grounded_observation_agent import GroundedObservationAgent

    packet = EvidencePacket.model_validate(packet_payload)
    agent = GroundedObservationAgent(profile_name=profile_name)
    try:
        observations = agent.analyze_evidence_packet(packet, profile_name)
        status = "completed"
        error = None
    except Exception as exc:
        observations = []
        status = "failed"
        error = {"type": exc.__class__.__name__, "message": str(exc)}

    artifact = getattr(agent, "last_agentic_observation_artifact", None) or {}
    return {
        "profile_name": profile_name,
        "packet_id": packet.packet_id,
        "packet_source_quality": (packet.run_metadata or {}).get("source_quality"),
        "packet_fact_count": len(packet.facts),
        "packet_snippet_count": len(packet.snippets),
        "status": status,
        "error": error,
        "accepted_observation_count": len(observations),
        "accepted_observations": [_json_safe(row) for row in observations],
        "artifact": _json_safe(artifact),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real Codex-backed judgment agents against persisted evidence packets without mutating the database."
    )
    parser.add_argument("--db", required=True, type=Path, help="Read-only SQLite evidence database.")
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument("--profiles", nargs="+", default=list(DEFAULT_PROFILES))
    parser.add_argument("--codex-executable", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--model", default=os.getenv("ALPHA_POD_CODEX_MODEL", "gpt-5.5"))
    parser.add_argument("--effort", default=os.getenv("ALPHA_POD_CODEX_EFFORT", "low"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "agent_evaluations" / "msft_real",
    )
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if args.codex_executable is not None and not args.codex_executable.resolve().is_file():
        raise FileNotFoundError(args.codex_executable)
    if args.codex_home is not None:
        codex_home = args.codex_home.resolve()
        if not codex_home.is_dir() or not (codex_home / "auth.json").is_file():
            raise FileNotFoundError(f"Codex home must contain auth.json: {codex_home}")

    os.environ["ALPHA_POD_AGENT_BACKEND"] = "codex"
    os.environ["ALPHA_POD_CODEX_MODEL"] = str(args.model)
    os.environ["ALPHA_POD_CODEX_EFFORT"] = str(args.effort)
    os.environ["ALPHA_POD_CODEX_ALLOW_FALLBACK"] = "0"
    os.environ.setdefault("ALPHA_POD_CODEX_TIMEOUT_SECONDS", "300")
    if args.codex_executable is not None:
        os.environ["ALPHA_POD_CODEX_EXECUTABLE"] = str(args.codex_executable.resolve())
    if args.codex_home is not None:
        os.environ["CODEX_HOME"] = str(args.codex_home.resolve())

    ticker = str(args.ticker).upper().strip()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    results: list[dict[str, Any]] = []
    try:
        for profile_name in args.profiles:
            packet = _load_latest_packet(conn, ticker=ticker, profile_name=str(profile_name))
            if packet is None:
                result = {
                    "profile_name": str(profile_name),
                    "status": "missing_packet",
                    "error": {"type": "MissingPacket", "message": "No matching persisted packet."},
                    "accepted_observation_count": 0,
                    "accepted_observations": [],
                    "artifact": {},
                }
            else:
                result = _evaluate_profile(packet, str(profile_name))
            results.append(result)
            profile_path = output_dir / f"{run_id}-{profile_name}.json"
            profile_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(
                f"{profile_name}: status={result['status']} "
                f"accepted={result['accepted_observation_count']} artifact={profile_path}"
            )
    finally:
        conn.close()

    summary = {
        "run_id": run_id,
        "ticker": ticker,
        "source_db": str(db_path),
        "source_db_sha256": _sha256(db_path),
        "codex_executable": os.environ.get("ALPHA_POD_CODEX_EXECUTABLE"),
        "codex_home": os.environ.get("CODEX_HOME"),
        "codex_model": str(args.model),
        "codex_effort": str(args.effort),
        "codex_timeout_seconds": int(os.environ["ALPHA_POD_CODEX_TIMEOUT_SECONDS"]),
        "profile_count": len(results),
        "completed_count": sum(result["status"] == "completed" for result in results),
        "failed_count": sum(result["status"] == "failed" for result in results),
        "accepted_observation_count": sum(int(result["accepted_observation_count"]) for result in results),
        "results": [
            {
                "profile_name": result["profile_name"],
                "status": result["status"],
                "accepted_observation_count": result["accepted_observation_count"],
                "error": result.get("error"),
                "rejection_reasons": (result.get("artifact") or {}).get("rejection_reasons") or [],
            }
            for result in results
        ],
    }
    summary_path = output_dir / f"{run_id}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"summary={summary_path}")
    return 1 if summary["failed_count"] or summary["completed_count"] != len(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

