from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PWCLI = "/mnt/c/Users/patri/.codex/skills/playwright/scripts/playwright_cli.sh"
OUTPUT_ROOT = REPO_ROOT / "output" / "playwright" / "route-matrix"
DEFAULT_BASE_URL = "http://127.0.0.1:4173"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api"
DEFAULT_BROWSER = "msedge" if sys.platform.startswith("win") else "firefox"
PROFESSIONAL_MODEL_STATES = {
    "UNVERIFIED",
    "BLOCKED",
    "NEEDS_PM_REVIEW",
    "PARTIAL",
    "FULL",
}
PROFESSIONAL_MODEL_PROBES = {
    "state": "professional-model-state",
    "decision_ready": "professional-model-decision-ready",
    "source_run_id": "professional-model-source-run-id",
    "source_hash": "professional-model-source-hash",
    "workbook_hash": "professional-model-workbook-hash",
    "calculation_status": "professional-model-calculation-status",
    "blocker_count": "professional-model-blocker-count",
    "sheet_count": "professional-model-sheet-count",
}


@dataclass(frozen=True)
class RouteReview:
    name: str
    url: str
    required_text: tuple[str, ...]
    forbidden_text: tuple[str, ...] = ()
    api_path: str | None = None


ROUTES: tuple[RouteReview, ...] = (
    RouteReview("watchlist", "http://127.0.0.1:4173/watchlist", ("Universe Tracker", "Ranked Universe", "Last Updated")),
    RouteReview("overview", "http://127.0.0.1:4173/ticker/CALM/overview", ("OVERVIEW", "Variant Thesis", "Valuation Pulse")),
    RouteReview(
        "valuation-summary",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=Summary",
        ("Scenario Summary", "Weighted IV", "Why This Matters"),
        ("Scenario summary will appear here", "Analyst Target: —"),
    ),
    RouteReview(
        "valuation-dcf",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=DCF",
        ("Forecast Bridge", "Health Flags", "Sensitivity Tables"),
        ("No rows available.",),
    ),
    RouteReview(
        "valuation-comparables",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=Comparables",
        ("Valuation Metric", "Target vs Peer Medians", "Football Field"),
        ("No rows available.",),
    ),
    RouteReview(
        "valuation-multiples",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=Multiples",
        ("Historical Multiples", "Historical Multiple Series", "Series Table"),
        ("No historical multiple summaries available.",),
    ),
    RouteReview(
        "valuation-assumptions",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=Assumptions",
        ("Tracked Fields", "Preview Assumptions", "Audit History"),
        ("Current price — | Current IV —", "No rows available."),
    ),
    RouteReview(
        "valuation-wacc",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=WACC",
        ("Methodology mode", "Available Methods", "WACC Audit History"),
        ("No rows available.",),
    ),
    RouteReview(
        "valuation-recommendations",
        "http://127.0.0.1:4173/ticker/CALM/valuation?view=Recommendations",
        ("Recommendations", "What-If Preview", "Apply Approved → valuation_overrides.yaml"),
    ),
    RouteReview(
        "valuation-professional-model",
        "http://127.0.0.1:4173/ticker/MSFT/valuation?view=Professional%20Model",
        ("Professional Model Readiness", "Full-State Checklist", "Workbook Sheet Review"),
        (
            "Loading Professional Model",
            "Professional model data is unavailable",
            "Unknown readiness state",
            "Readiness state missing",
        ),
        "/tickers/MSFT/professional-model",
    ),
    RouteReview("market", "http://127.0.0.1:4173/ticker/CALM/market", ("MARKET", "Historical Brief", "Quarterly Materiality")),
    RouteReview("research", "http://127.0.0.1:4173/ticker/CALM/research", ("RESEARCH", "Tracker Summary", "Open Questions")),
    RouteReview("audit", "http://127.0.0.1:4173/ticker/CALM/audit", ("AUDIT", "DCF Audit", "Comparables")),
)

RESULT_PATTERNS = {
    "screenshot": re.compile(r"\[Screenshot of viewport\]\((?P<path>[^)]+)\)"),
    "snapshot": re.compile(r"\[Snapshot\]\((?P<path>[^)]+)\)"),
    "console": re.compile(r"\[Console\]\((?P<path>[^)]+)\)"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review the canonical React route matrix.")
    parser.add_argument(
        "--browser",
        default=os.environ.get("PLAYWRIGHT_BROWSER", DEFAULT_BROWSER),
        help="Browser or channel for playwright-cli.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("REACT_BASE_URL", DEFAULT_BASE_URL),
        help="Frontend base URL.",
    )
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("REACT_API_BASE_URL", DEFAULT_API_BASE_URL),
        help="Direct API base URL used for rendered-state agreement checks.",
    )
    return parser.parse_args(argv)


def route_url_for_base(route: RouteReview, base_url: str) -> str:
    parsed = urlsplit(route.url)
    target = urljoin(f"{base_url.rstrip('/')}/", parsed.path.lstrip("/"))
    if parsed.query:
        target = f"{target}?{parsed.query}"
    if parsed.fragment:
        target = f"{target}#{parsed.fragment}"
    return target


def url_signature(url: str) -> tuple[str, str, str, tuple[tuple[str, str], ...], str]:
    parsed = urlsplit(url)
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        unquote(parsed.path),
        tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True))),
        parsed.fragment,
    )


def urls_match(actual: str, expected: str) -> bool:
    return url_signature(actual) == url_signature(expected)


def repo_path_from_cli(ref: str) -> Path:
    ref = ref.strip()
    if ref.startswith("."):
        return REPO_ROOT / ref
    return Path(ref)


def normalize_candidate_path(candidate: str) -> str:
    if os.path.exists(candidate):
        return candidate
    if candidate.startswith("/mnt/") and os.name == "nt":
        drive = candidate[5].upper()
        rest = candidate[6:].replace("/", "\\").lstrip("\\")
        windows_candidate = f"{drive}:\\{rest}"
        if os.path.exists(windows_candidate):
            return windows_candidate
    return candidate


def resolve_pwcli_command() -> list[str]:
    candidates: list[str] = []
    env_override = os.environ.get("PWCLI")
    if env_override:
        candidates.append(env_override)

    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(str(Path(codex_home) / "skills" / "playwright" / "scripts" / "playwright_cli.sh"))

    candidates.extend(
        [
            DEFAULT_PWCLI,
            r"C:\Users\patri\.codex\skills\playwright\scripts\playwright_cli.sh",
            "playwright-cli",
        ]
    )

    for candidate in candidates:
        normalized = normalize_candidate_path(candidate)
        if normalized.endswith(".sh"):
            if os.path.exists(normalized):
                bash_path = shutil.which("bash")
                if bash_path:
                    return [bash_path, normalized]
        elif os.path.exists(normalized):
            return [normalized]
        else:
            resolved = shutil.which(normalized)
            if resolved:
                return [resolved]

    npx_path = shutil.which("npx")
    if npx_path:
        return [npx_path, "playwright-cli"]

    raise FileNotFoundError(
        "Missing Playwright CLI wrapper. Set PWCLI or install playwright-cli on PATH."
    )


def run_pwcli(env: dict[str, str], pwcli_cmd: list[str], *args: str) -> str:
    process = subprocess.run(
        [*pwcli_cmd, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"PWCLI {' '.join(args)} failed\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return process.stdout


def extract_path(label: str, output: str) -> Path:
    match = RESULT_PATTERNS[label].search(output)
    if not match:
        raise RuntimeError(f"Unable to find {label} path in output:\n{output}")
    return repo_path_from_cli(match.group("path"))


def parse_eval_json(output: str) -> object:
    payload_text = output.split("### Result", 1)[-1]
    payload_text = payload_text.split("### Ran Playwright code", 1)[0].strip()
    return json.loads(payload_text)


def fetch_json_object(url: str, timeout_s: float = 30.0) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            payload_text = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Direct API request failed ({exc.code}) for {url}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Direct API request failed for {url}: {exc.reason}") from exc

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Direct API response was not JSON for {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Direct API response must be an object for {url}")
    return payload


def first_supplied(*values: object) -> object | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def required_string(value: object, field: str) -> str:
    if value is None:
        raise RuntimeError(f"Direct API field is missing: {field}")
    normalized = str(value).strip()
    if not normalized:
        raise RuntimeError(f"Direct API field is empty: {field}")
    return normalized


def nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"Direct API {field} must be a nonnegative integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Direct API {field} must be a nonnegative integer") from exc
    if normalized < 0:
        raise RuntimeError(f"Direct API {field} must be a nonnegative integer")
    return normalized


def _structured_blocker_count(blockers: dict[str, object]) -> int:
    groups = blockers.get("groups")
    counts = blockers.get("counts")
    if not isinstance(groups, dict):
        raise RuntimeError("Direct API blockers.groups must be an object")
    if not isinstance(counts, dict):
        raise RuntimeError("Direct API blockers.counts must be an object")
    if set(groups) != set(counts):
        raise RuntimeError(
            "Direct API blockers.groups and blockers.counts must use the same keys"
        )

    grouped_total = 0
    counted_total = 0
    for group_name, entries in groups.items():
        if not isinstance(entries, list):
            raise RuntimeError(f"Direct API blockers.groups.{group_name} must be an array")
        group_count = nonnegative_integer(counts[group_name], f"blockers.counts.{group_name}")
        if group_count != len(entries):
            raise RuntimeError(
                f"Direct API blocker count mismatch for group {group_name}: "
                f"count={group_count}, entries={len(entries)}"
            )
        grouped_total += len(entries)
        counted_total += group_count

    total = nonnegative_integer(blockers.get("total"), "blockers.total")
    if total != grouped_total or total != counted_total:
        raise RuntimeError(
            "Direct API blockers.total does not agree with blockers.groups and "
            "blockers.counts"
        )
    return total


def professional_model_blocker_count(payload: dict[str, object]) -> int:
    blockers = payload.get("blockers")
    if isinstance(blockers, dict) and any(
        field in blockers for field in ("groups", "counts", "total")
    ):
        return _structured_blocker_count(blockers)

    groups = payload.get("blocker_groups")
    if isinstance(groups, list):
        total = 0
        for group in groups:
            if not isinstance(group, dict):
                raise RuntimeError("Direct API blocker_groups entries must be objects")
            blockers = group.get("blockers")
            count = group.get("count")
            if count is not None:
                try:
                    total += int(count)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Direct API blocker group count must be an integer") from exc
            elif isinstance(blockers, list):
                total += len(blockers)
            else:
                raise RuntimeError("Direct API blocker group must supply count or blockers")
        return total
    if isinstance(groups, dict):
        total = 0
        for blockers in groups.values():
            if not isinstance(blockers, list):
                raise RuntimeError("Direct API blocker group mapping values must be arrays")
            total += len(blockers)
        return total

    blockers = payload.get("blockers")
    if blockers is None:
        return 0
    if not isinstance(blockers, list):
        raise RuntimeError("Direct API blockers must be an array")
    return len(blockers)


def normalize_professional_model_summary(payload: dict[str, object]) -> dict[str, object]:
    state = required_string(
        first_supplied(payload.get("normalized_state"), payload.get("state")),
        "normalized_state",
    )
    if state not in PROFESSIONAL_MODEL_STATES:
        raise RuntimeError(f"Direct API returned unknown readiness state: {state}")

    decision_readiness = payload.get("decision_readiness")
    decision_ready = (
        decision_readiness
        if isinstance(decision_readiness, bool)
        else payload.get("decision_ready")
    )
    if not isinstance(decision_ready, bool):
        raise RuntimeError("Direct API decision_readiness must be a boolean")

    legacy_decision_ready = payload.get("decision_ready")
    if (
        isinstance(decision_readiness, bool)
        and isinstance(legacy_decision_ready, bool)
        and decision_readiness != legacy_decision_ready
    ):
        raise RuntimeError("Direct API decision_readiness and decision_ready disagree")

    artifact_value = payload.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else {}
    hashes_value = payload.get("hashes")
    hashes = hashes_value if isinstance(hashes_value, dict) else {}
    source_run_id = required_string(
        first_supplied(
            payload.get("model_run_id"),
            artifact.get("source_run_id"),
            payload.get("source_run_id"),
        ),
        "model_run_id",
    )
    source_hash = required_string(
        first_supplied(
            hashes.get("source_sha256"),
            artifact.get("source_hash"),
            payload.get("source_hash"),
        ),
        "hashes.source_sha256",
    )
    workbook_hash = required_string(
        first_supplied(
            hashes.get("workbook_sha256"),
            artifact.get("workbook_hash"),
            payload.get("workbook_hash"),
        ),
        "hashes.workbook_sha256",
    )

    verification = payload.get("calculation_verification")
    calculation_status: object | None = None
    if isinstance(verification, str):
        calculation_status = verification
    elif isinstance(verification, dict):
        calculation_status = first_supplied(verification.get("state"), verification.get("status"))
        if calculation_status is None and verification.get("verified") is True:
            calculation_status = "VERIFIED"
        elif calculation_status is None and verification.get("verified") is False:
            calculation_status = "NOT_VERIFIED"
    calculation_status_text = required_string(
        calculation_status,
        "calculation_verification.state",
    )

    sheets = payload.get("sheets")
    if not isinstance(sheets, list):
        raise RuntimeError("Direct API sheets must be an array")

    return {
        "state": state,
        "decision_ready": decision_ready,
        "source_run_id": source_run_id,
        "source_hash": source_hash,
        "workbook_hash": workbook_hash,
        "calculation_status": calculation_status_text,
        "blocker_count": professional_model_blocker_count(payload),
        "sheet_count": len(sheets),
    }


def read_professional_model_probes(
    env: dict[str, str],
    pwcli_cmd: list[str],
) -> dict[str, object]:
    script = """() => {
      const probes = %s;
      return Object.fromEntries(
        Object.entries(probes).map(([field, testId]) => {
          const element = document.querySelector('[data-testid="' + testId + '"]');
          return [
            field,
            element
              ? {
                  data_value: element.getAttribute("data-value"),
                  text: (element.textContent || "").trim(),
                }
              : null,
          ];
        }),
      );
    }""" % json.dumps(PROFESSIONAL_MODEL_PROBES)
    result = parse_eval_json(run_pwcli(env, pwcli_cmd, "eval", script))
    if not isinstance(result, dict):
        raise RuntimeError("Rendered professional-model probe must be an object")
    return result


def normalize_rendered_probe(field: str, probe: object) -> object:
    if not isinstance(probe, dict):
        raise RuntimeError(f"Rendered probe is missing: {PROFESSIONAL_MODEL_PROBES[field]}")
    raw_value = probe.get("data_value")
    if raw_value is None:
        raise RuntimeError(
            f"Rendered probe lacks data-value: {PROFESSIONAL_MODEL_PROBES[field]}"
        )
    text = str(raw_value).strip()
    if field == "decision_ready":
        if text == "true":
            return True
        if text == "false":
            return False
        raise RuntimeError("Rendered decision_ready data-value must be true or false")
    if field in {"blocker_count", "sheet_count"}:
        try:
            return int(text)
        except ValueError as exc:
            raise RuntimeError(f"Rendered {field} data-value must be an integer") from exc
    return text


def verify_professional_model_agreement(
    env: dict[str, str],
    pwcli_cmd: list[str],
    api_url: str,
) -> dict[str, object]:
    payload = fetch_json_object(api_url)
    expected = normalize_professional_model_summary(payload)
    raw_rendered = read_professional_model_probes(env, pwcli_cmd)

    rendered: dict[str, object] = {}
    probe_text: dict[str, object] = {}
    errors: list[str] = []
    for field in PROFESSIONAL_MODEL_PROBES:
        probe = raw_rendered.get(field)
        if isinstance(probe, dict):
            probe_text[field] = probe.get("text")
        try:
            rendered[field] = normalize_rendered_probe(field, probe)
        except RuntimeError as exc:
            errors.append(str(exc))

    mismatches = {
        field: {"api": expected[field], "rendered": rendered.get(field)}
        for field in expected
        if field in rendered and expected[field] != rendered[field]
    }
    if expected["sheet_count"] != 26:
        errors.append(
            f"Direct API sheet count must be 26, got {expected['sheet_count']}"
        )

    return {
        "api_url": api_url,
        "matches": not errors and not mismatches,
        "api_values": expected,
        "rendered_values": rendered,
        "rendered_text": probe_text,
        "mismatches": mismatches,
        "errors": errors,
    }


def wait_for_required_text(
    env: dict[str, str],
    pwcli_cmd: list[str],
    required_text: tuple[str, ...],
    forbidden_text: tuple[str, ...],
    timeout_s: float = 30.0,
) -> dict[str, object]:
    script = """() => ({ url: window.location.href, text: document.body.innerText, title: document.title })"""
    deadline = time.time() + timeout_s
    last_result: dict[str, object] = {}
    while time.time() < deadline:
        output = run_pwcli(env, pwcli_cmd, "eval", script)
        try:
            result = parse_eval_json(output)
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        if not isinstance(result, dict):
            time.sleep(1)
            continue
        last_result = result
        body = str(result.get("text", ""))
        body_lower = body.lower()
        if (
            all(marker.lower() in body_lower for marker in required_text)
            and all(marker.lower() not in body_lower for marker in forbidden_text)
            and "failed to load" not in body_lower
            and "loading valuation data..." not in body_lower
        ):
            return result
        time.sleep(1)
    raise RuntimeError(
        f"Timed out waiting for markers {required_text} and excluding {forbidden_text}; "
        f"last body snippet:\n{str(last_result.get('text', ''))[:1500]}"
    )


def ensure_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        pwcli_cmd = resolve_pwcli_command()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.setdefault("HOME", "/tmp/codex-playwright-home")
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("TMP", "/tmp")
    env.setdefault("TEMP", "/tmp")

    output_dir = ensure_output_dir()
    manifest_path = output_dir / "manifest.json"
    results: list[dict[str, object]] = []
    failed_routes: list[str] = []

    for route in ROUTES:
        route_url = route_url_for_base(route, args.base_url)
        print(f"[route-review] {route.name} -> {route_url}")
        route_result: dict[str, object] = {
            **asdict(route),
            "url": route_url,
            "browser": args.browser,
            "page_url": None,
            "page_title": None,
            "markers_valid": False,
            "url_matches": False,
            "console_clean": False,
        }
        validation_errors: list[str] = []
        opened = False

        try:
            run_pwcli(env, pwcli_cmd, "open", route_url, "--browser", args.browser)
            opened = True
            body_state = wait_for_required_text(
                env,
                pwcli_cmd,
                route.required_text,
                route.forbidden_text,
            )
            page_url = str(body_state.get("url", ""))
            route_result.update(
                {
                    "page_url": page_url,
                    "page_title": body_state.get("title"),
                    "markers_valid": True,
                    "url_matches": urls_match(page_url, route_url),
                }
            )
            if not route_result["url_matches"]:
                validation_errors.append(
                    f"Expected exact URL {route_url}, browser reported {page_url}"
                )

            if route.api_path:
                api_url = urljoin(
                    f"{args.api_base_url.rstrip('/')}/",
                    route.api_path.lstrip("/"),
                )
                try:
                    agreement = verify_professional_model_agreement(
                        env,
                        pwcli_cmd,
                        api_url,
                    )
                except (RuntimeError, OSError, json.JSONDecodeError) as exc:
                    agreement = {
                        "api_url": api_url,
                        "matches": False,
                        "error": str(exc),
                    }
                route_result["api_render_agreement"] = agreement
                if not agreement.get("matches"):
                    validation_errors.append(
                        "Direct API values do not agree with rendered professional-model state"
                    )

            snapshot_output = run_pwcli(env, pwcli_cmd, "snapshot")
            console_output = run_pwcli(env, pwcli_cmd, "console")
            screenshot_output = run_pwcli(env, pwcli_cmd, "screenshot")

            snapshot_path = extract_path("snapshot", snapshot_output)
            console_path = extract_path("console", console_output)
            screenshot_path = extract_path("screenshot", screenshot_output)

            route_dir = output_dir / route.name
            route_dir.mkdir(parents=True, exist_ok=True)
            copied_snapshot = route_dir / snapshot_path.name
            copied_console = route_dir / console_path.name
            copied_screenshot = route_dir / screenshot_path.name
            shutil.copy2(snapshot_path, copied_snapshot)
            shutil.copy2(console_path, copied_console)
            shutil.copy2(screenshot_path, copied_screenshot)

            console_text = console_path.read_text(encoding="utf-8", errors="ignore")
            console_clean = "Errors: 0" in console_text and "Warnings: 0" in console_text
            route_result.update(
                {
                    "console_clean": console_clean,
                    "screenshot": str(copied_screenshot.relative_to(REPO_ROOT)),
                    "snapshot": str(copied_snapshot.relative_to(REPO_ROOT)),
                    "console": str(copied_console.relative_to(REPO_ROOT)),
                }
            )
            if not console_clean:
                validation_errors.append("Browser console contains errors or warnings")
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            validation_errors.append(str(exc))
        finally:
            if opened:
                try:
                    run_pwcli(env, pwcli_cmd, "close")
                except RuntimeError as exc:
                    validation_errors.append(f"Browser close failed: {exc}")

        route_result["validation_errors"] = validation_errors
        route_result["status"] = "failed" if validation_errors else "passed"
        if validation_errors:
            failed_routes.append(route.name)
            print(
                f"[route-review] FAILED {route.name}: {'; '.join(validation_errors)}",
                file=sys.stderr,
            )
        results.append(route_result)
        manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary = {
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
        "routes": len(results),
        "failed_routes": failed_routes,
    }
    print(json.dumps(summary, indent=2))
    return 1 if failed_routes else 0


if __name__ == "__main__":
    raise SystemExit(main())
