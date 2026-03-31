from __future__ import annotations

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


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PWCLI = "/mnt/c/Users/patri/.codex/skills/playwright/scripts/playwright_cli.sh"
OUTPUT_ROOT = REPO_ROOT / "output" / "playwright" / "route-matrix"


@dataclass(frozen=True)
class RouteReview:
    name: str
    url: str
    required_text: tuple[str, ...]
    forbidden_text: tuple[str, ...] = ()


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
    RouteReview("market", "http://127.0.0.1:4173/ticker/CALM/market", ("MARKET", "Historical Brief", "Quarterly Materiality")),
    RouteReview("research", "http://127.0.0.1:4173/ticker/CALM/research", ("RESEARCH", "Tracker Summary", "Open Questions")),
    RouteReview("audit", "http://127.0.0.1:4173/ticker/CALM/audit", ("AUDIT", "DCF Audit", "Comparables")),
)

RESULT_PATTERNS = {
    "screenshot": re.compile(r"\[Screenshot of viewport\]\((?P<path>[^)]+)\)"),
    "snapshot": re.compile(r"\[Snapshot\]\((?P<path>[^)]+)\)"),
    "console": re.compile(r"\[Console\]\((?P<path>[^)]+)\)"),
}


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
        payload_text = output.split("### Result", 1)[-1]
        try:
            result = json.loads(payload_text.split("### Ran Playwright code", 1)[0].strip())
        except json.JSONDecodeError:
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


def main() -> int:
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
    results: list[dict[str, object]] = []

    for route in ROUTES:
        print(f"[route-review] {route.name} -> {route.url}")
        run_pwcli(env, pwcli_cmd, "open", route.url, "--browser", "firefox")
        body_state = wait_for_required_text(env, pwcli_cmd, route.required_text, route.forbidden_text)
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
        results.append(
            {
                **asdict(route),
                "page_url": body_state.get("url"),
                "page_title": body_state.get("title"),
                "console_clean": console_clean,
                "screenshot": str(copied_screenshot.relative_to(REPO_ROOT)),
                "snapshot": str(copied_snapshot.relative_to(REPO_ROOT)),
                "console": str(copied_console.relative_to(REPO_ROOT)),
            }
        )
        run_pwcli(env, pwcli_cmd, "close")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "manifest": str(manifest_path), "routes": len(results)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
