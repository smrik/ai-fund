from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GUIDED_OUTPUT_DIR = ROOT / "output" / "guided_workups"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _print_json(payload: Any) -> None:
    print(json.dumps(_jsonable(payload), indent=2, default=str))


def _target_pack(preview_payload: dict[str, Any], targets: list[str]) -> dict[str, Any]:
    item = preview_payload.get("item") or {}
    pack = dict(item.get("pm_edited_proposal_pack") or item.get("proposal_pack") or {})
    proposals = []
    target_by_name: dict[str, float] = {}
    for raw in targets:
        if "=" not in raw:
            raise SystemExit(f"Invalid --target {raw!r}; expected field=value")
        name, value = raw.split("=", 1)
        target_by_name[name.strip()] = float(value)
    for proposal in pack.get("proposals") or []:
        edited = dict(proposal)
        name = str(edited.get("assumption_name") or "")
        if name in target_by_name:
            edited["proposal_mode"] = "target"
            edited["proposed_target_value"] = target_by_name[name]
            edited["proposed_delta"] = None
        proposals.append(edited)
    pack["proposals"] = proposals
    return pack


def _fmt_money(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _fmt_pct(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):+.1f}%"
    except Exception:
        return "n/a"


def _decision_commands(ticker: str, item: dict[str, Any]) -> list[str]:
    item_id = int(item["item_id"])
    base = f"python scripts/manual/pm_decision_queue.py --ticker {ticker}"
    status = str(item.get("status") or "").lower()
    if status not in {"pending", "previewed"}:
        return [f"# No direct mutation command: item {item_id} is {status or 'not actionable'}."]
    commands = [
        f'{base} defer --item-id {item_id} --reason "Needs PM review"',
        f'{base} reject --item-id {item_id} --reason "Not decision-useful"',
    ]
    if item.get("item_type") == "assumption_change_pack":
        commands.insert(0, f"{base} preview --item-id {item_id}")
        pack = item.get("pm_edited_proposal_pack") or item.get("proposal_pack") or {}
        for proposal in pack.get("proposals") or []:
            if isinstance(proposal, dict) and proposal.get("assumption_name"):
                commands.append(
                    f"{base} edit-target --item-id {item_id} "
                    f"--target {proposal.get('assumption_name')}=<value>"
                )
        commands.append(f"{base} approve-apply --item-id {item_id} --confirm APPLY")
    return commands


def _find_review_packet(ticker: str, item_id: int, output_dir: Path) -> str | None:
    ticker_dir = output_dir / ticker
    if not ticker_dir.exists():
        return None
    needle = f"Item {item_id}:"
    for path in sorted(ticker_dir.glob(f"{ticker}-*-review.md"), reverse=True):
        try:
            if needle in path.read_text(encoding="utf-8"):
                return str(path)
        except OSError:
            continue
    return None


def _latest_artifact(ticker: str, output_dir: Path, pattern: str) -> str | None:
    ticker_dir = output_dir / ticker
    if not ticker_dir.exists():
        return None
    paths = sorted(ticker_dir.glob(pattern), reverse=True)
    return str(paths[0]) if paths else None


def _latest_excel_model(ticker: str) -> str | None:
    export_dir = ROOT / "data" / "exports" / "generated" / "ticker" / ticker
    if not export_dir.exists():
        return None
    paths = sorted(export_dir.glob(f"*-excelmodel-*/*_excel_model.xlsx"), reverse=True)
    return str(paths[0]) if paths else None


def _preview_summary(preview_payload: dict[str, Any] | None) -> list[str]:
    if not preview_payload:
        return []
    preview_payload = _jsonable(preview_payload)
    if isinstance(preview_payload, dict) and preview_payload.get("error"):
        return [f"- Preview error: {preview_payload.get('error')}"]
    preview = (preview_payload or {}).get("preview") or {}
    current_iv = preview.get("current_iv") or {}
    proposed_iv = preview.get("proposed_iv") or {}
    delta_pct = preview.get("delta_pct") or {}
    lines = [
        f"- Base IV preview: {_fmt_money(current_iv.get('base'))} -> "
        f"{_fmt_money(proposed_iv.get('base'))} ({_fmt_pct(delta_pct.get('base'))})"
    ]
    for name, values in (preview.get("resolved_values") or {}).items():
        values = values or {}
        lines.append(f"- `{name}`: {values.get('current_value')} -> {values.get('proposed_value')}")
    return lines


def _stored_preview_summary(item: dict[str, Any]) -> list[str]:
    adapter_links = item.get("adapter_links") or {}
    manual_values = adapter_links.get("last_preview_manual_values") or {}
    if not manual_values:
        return []
    lines = [
        f"- Stored preview from: {adapter_links.get('last_preview_at') or 'unknown time'}",
        "- Fresh preview unavailable for the current status; these are the last resolved target values.",
    ]
    for name, value in manual_values.items():
        lines.append(f"- `{name}` target: {value}")
    return lines


def render_review_index(
    ticker: str,
    queue_payload: dict[str, Any],
    *,
    previews: dict[int, dict[str, Any] | None],
    output_dir: Path,
) -> str:
    items = queue_payload.get("items") or []
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    lines = [
        f"# {ticker} PM Queue Review Index",
        "",
        "This is the durable PM review surface for all current queue items for the ticker.",
        "",
        "## Companion Artifacts",
        "",
    ]
    companion_artifacts = [
        ("Latest Excel model", _latest_excel_model(ticker)),
        ("Latest Analyst Prep", _latest_artifact(ticker, output_dir, f"{ticker}-*-analyst-prep.md")),
        ("Latest session summary", _latest_artifact(ticker, output_dir, f"{ticker}-????????T??????Z.md")),
        ("Latest JSON bundle", _latest_artifact(ticker, output_dir, f"{ticker}-????????T??????Z.json")),
    ]
    found_artifact = False
    for label, path in companion_artifacts:
        if path:
            found_artifact = True
            lines.append(f"- {label}: `{path}`")
    if not found_artifact:
        lines.append("- No companion artifacts found in the guided output directory yet.")
    lines.extend(
        [
            "",
            "## Queue Status",
            "",
        ]
    )
    if status_counts:
        for status, count in sorted(status_counts.items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- No queue items found.")
    lines.extend(["", "## Items", ""])

    for item in items:
        item_id = int(item["item_id"])
        metadata = item.get("metadata") or {}
        lines.extend(
            [
                f"### Item {item_id}: {item.get('title')}",
                "",
                f"- Status: {item.get('status')}",
                f"- Type: {item.get('item_type')}",
                f"- Profile: {item.get('profile_name')}",
                f"- Importance: {item.get('qualitative_importance') or 'n/a'}",
                f"- Summary: {item.get('summary')}",
            ]
        )
        if metadata.get("pm_question"):
            lines.append(f"- PM question: {metadata.get('pm_question')}")
        review_packet = _find_review_packet(ticker, item_id, output_dir)
        lines.append(f"- Review packet: `{review_packet or 'not generated yet; use this index row'}`")
        if item.get("decision_history"):
            lines.append("- Decision history:")
            for event in item.get("decision_history") or []:
                lines.append(
                    f"  - {event.get('event')} by {event.get('actor')} at "
                    f"{event.get('event_ts')}: {event.get('reason') or 'n/a'}"
                )
        preview_lines = _preview_summary(previews.get(item_id))
        if preview_lines and any("Preview error:" in line for line in preview_lines):
            stored_preview_lines = _stored_preview_summary(item)
            if stored_preview_lines:
                preview_lines = stored_preview_lines
        if preview_lines:
            lines.extend(["", "Preview:"])
            lines.extend(preview_lines)
        lines.extend(["", "Commands:", "", "```powershell"])
        lines.extend(_decision_commands(ticker, item))
        lines.extend(["```", ""])

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and decide PM Decision Queue items.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--live-market",
        action="store_true",
        help="Allow live market-data calls while previewing. Default uses the local market cache.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--status")

    index_parser = sub.add_parser("review-index")
    index_parser.add_argument("--status")
    index_parser.add_argument("--output")
    index_parser.add_argument("--output-dir", default=str(GUIDED_OUTPUT_DIR))

    preview_parser = sub.add_parser("preview")
    preview_parser.add_argument("--item-id", type=int, required=True)

    edit_parser = sub.add_parser("edit-target")
    edit_parser.add_argument("--item-id", type=int, required=True)
    edit_parser.add_argument("--target", action="append", default=[], help="field=value; repeat for multiple fields")

    reject_parser = sub.add_parser("reject")
    reject_parser.add_argument("--item-id", type=int, required=True)
    reject_parser.add_argument("--reason", required=True)

    defer_parser = sub.add_parser("defer")
    defer_parser.add_argument("--item-id", type=int, required=True)
    defer_parser.add_argument("--reason", required=True)

    approve_parser = sub.add_parser("approve-apply")
    approve_parser.add_argument("--item-id", type=int, required=True)
    approve_parser.add_argument("--confirm", required=True, help="Must be APPLY")

    args = parser.parse_args(argv)
    ticker = args.ticker.upper().strip()
    if not args.live_market:
        os.environ.setdefault("ALPHA_POD_MARKET_CACHE_ONLY", "1")
        os.environ.setdefault("ALPHA_POD_ALLOW_STALE_MARKET_CACHE", "1")

    from api.main import (
        apply_pm_decision_queue_payload,
        approve_pm_decision_queue_payload,
        defer_pm_decision_queue_payload,
        edit_pm_decision_queue_payload,
        list_pm_decision_queue_payload,
        preview_pm_decision_queue_payload,
        reject_pm_decision_queue_payload,
    )

    if args.command == "list":
        _print_json(list_pm_decision_queue_payload(ticker, status=args.status))
        return 0
    if args.command == "review-index":
        payload = list_pm_decision_queue_payload(ticker, status=args.status)
        previews: dict[int, dict[str, Any] | None] = {}
        for item in payload.get("items") or []:
            item_id = int(item["item_id"])
            if item.get("item_type") != "assumption_change_pack":
                previews[item_id] = None
                continue
            try:
                previews[item_id] = preview_pm_decision_queue_payload(ticker, item_id)
            except Exception as exc:
                previews[item_id] = {"error": str(exc)}
        output_dir = Path(args.output_dir)
        markdown = render_review_index(ticker, payload, previews=previews, output_dir=output_dir)
        output_path = Path(args.output) if args.output else output_dir / ticker / f"{ticker}-queue-review-index.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown + "\n", encoding="utf-8")
        print(str(output_path))
        return 0
    if args.command == "preview":
        _print_json(preview_pm_decision_queue_payload(ticker, args.item_id))
        return 0
    if args.command == "edit-target":
        preview = preview_pm_decision_queue_payload(ticker, args.item_id)
        pack = _target_pack(preview, args.target)
        edited = edit_pm_decision_queue_payload(ticker, args.item_id, pack, actor="pm")
        _print_json(
            {
                "edited": edited,
                "preview": preview_pm_decision_queue_payload(ticker, args.item_id),
            }
        )
        return 0
    if args.command == "reject":
        _print_json(reject_pm_decision_queue_payload(ticker, args.item_id, actor="pm", reason=args.reason))
        return 0
    if args.command == "defer":
        _print_json(defer_pm_decision_queue_payload(ticker, args.item_id, actor="pm", reason=args.reason))
        return 0
    if args.command == "approve-apply":
        if args.confirm != "APPLY":
            raise SystemExit("--confirm must be APPLY")
        preview = preview_pm_decision_queue_payload(ticker, args.item_id)
        approved = approve_pm_decision_queue_payload(ticker, args.item_id, actor="pm")
        applied = apply_pm_decision_queue_payload(ticker, args.item_id, actor="pm")
        _print_json({"preview": preview, "approved": approved, "applied": applied})
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
