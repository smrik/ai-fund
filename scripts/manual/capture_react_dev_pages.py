import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output" / "playwright" / "dev-verify"
DEFAULT_BASE_URL = "http://127.0.0.1:4173"
DEFAULT_WIDTH = 1600
DEFAULT_HEIGHT = 1200


class CaptureRoute:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path

    @property
    def url(self) -> str:
        return f"{DEFAULT_BASE_URL.rstrip('/')}{self.path}"


ALL_ROUTES = (
    CaptureRoute("watchlist", "/watchlist"),
    CaptureRoute("overview", "/ticker/CALM/overview"),
    CaptureRoute("valuation-summary", "/ticker/CALM/valuation"),
    CaptureRoute("valuation-dcf", "/ticker/CALM/valuation?view=DCF"),
    CaptureRoute("valuation-multiples", "/ticker/CALM/valuation?view=Multiples"),
    CaptureRoute("valuation-recommendations", "/ticker/CALM/valuation?view=Recommendations"),
    CaptureRoute("market", "/ticker/CALM/market"),
    CaptureRoute("research", "/ticker/CALM/research"),
    CaptureRoute("audit", "/ticker/CALM/audit"),
)

SMOKE_ROUTE_NAMES = (
    "watchlist",
    "overview",
    "valuation-summary",
    "market",
    "research",
    "audit",
)


def select_routes(full: bool, one_page: str | None) -> tuple[CaptureRoute, ...]:
    route_by_name = {route.name: route for route in ALL_ROUTES}
    if one_page:
        try:
            return (route_by_name[one_page],)
        except KeyError as exc:
            known = ", ".join(route_by_name)
            raise ValueError(f"Unknown route '{one_page}'. Known routes: {known}") from exc
    if full:
        return ALL_ROUTES
    return tuple(route_by_name[name] for name in SMOKE_ROUTE_NAMES)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture quiet Playwright screenshots for the React dev server."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--full", action="store_true", help="Capture the full route set.")
    group.add_argument("--one-page", metavar="ROUTE", help="Capture only a single named route.")
    parser.add_argument(
        "--browser",
        default="msedge" if sys.platform.startswith("win") else "firefox",
        help="Browser or channel for playwright-cli.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Frontend base URL.")
    parser.add_argument("--wait-ms", type=int, default=1200, help="Extra settle delay in ms.")
    parser.add_argument(
        "--output-dir",
        help="Optional explicit output directory. Defaults to output/playwright/dev-verify/<timestamp>/",
    )
    parser.add_argument("--session", help="Optional explicit playwright-cli session name.")
    return parser.parse_args(argv)


def resolve_cli_command() -> list[str]:
    npx_path = shutil.which("npx")
    if npx_path:
        return [npx_path, "playwright-cli"]
    playwright_cli_path = shutil.which("playwright-cli")
    if playwright_cli_path:
        return [playwright_cli_path]
    raise FileNotFoundError("Missing playwright-cli. Install it or ensure `npx` is available on PATH.")


def build_output_dir(explicit: str | None) -> Path:
    if explicit:
        output_dir = Path(explicit)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = OUTPUT_ROOT / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        joined = " ".join(cmd)
        raise RuntimeError(
            f"Command failed: {joined}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def wait_for_settle(cmd: list[str], session: str, wait_ms: int) -> None:
    run_command(
        [*cmd, f"-s={session}", "run-code", f"async page => {{ await page.waitForLoadState('networkidle').catch(() => {{}}); await page.waitForTimeout({wait_ms}); }}"]
    )


def ensure_viewport(cmd: list[str], session: str) -> None:
    run_command(
        [*cmd, f"-s={session}", "run-code", f"async page => {{ await page.setViewportSize({{ width: {DEFAULT_WIDTH}, height: {DEFAULT_HEIGHT} }}); }}"]
    )


def capture_routes(
    cmd: list[str],
    session: str,
    routes: tuple[CaptureRoute, ...],
    output_dir: Path,
    *,
    browser: str,
    base_url: str,
    wait_ms: int,
) -> list[Path]:
    manifest = []
    screenshots = []

    first_route, *remaining = routes
    run_command([*cmd, f"-s={session}", "open", first_route.url, "--browser", browser])
    ensure_viewport(cmd, session)
    wait_for_settle(cmd, session, wait_ms)

    for idx, route in enumerate(routes):
        if idx > 0:
            run_command([*cmd, f"-s={session}", "goto", route.url])
            wait_for_settle(cmd, session, wait_ms)

        screenshot_path = output_dir / f"{route.name}.png"
        run_command([*cmd, f"-s={session}", "screenshot", "--filename", screenshot_path.as_posix(), "--full-page"])
        screenshots.append(screenshot_path)
        manifest.append(
            {
                "name": route.name,
                "url": route.url,
                "screenshot": str(screenshot_path.relative_to(REPO_ROOT)),
            }
        )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return screenshots


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        routes = select_routes(full=args.full, one_page=args.one_page)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        cmd = resolve_cli_command()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = build_output_dir(args.output_dir)
    session = args.session or f"react-dev-capture-{datetime.now().strftime('%H%M%S')}"

    try:
        screenshots = capture_routes(
            cmd,
            session,
            routes,
            output_dir,
            browser=args.browser,
            base_url=args.base_url,
            wait_ms=args.wait_ms,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        try:
            run_command([*cmd, f"-s={session}", "close"])
        except RuntimeError:
            pass

    for screenshot in screenshots:
        print(screenshot.relative_to(REPO_ROOT).as_posix())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
