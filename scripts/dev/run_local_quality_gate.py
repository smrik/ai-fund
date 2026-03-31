"""Run the repo's lightweight local quality gate."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ARCHITECTURE_TEST = "tests/test_architecture_boundaries.py"


def changed_python_files(base_ref: str, head_ref: str) -> list[str]:
	"""Return changed Python files between two refs."""
	completed = subprocess.run(
		["git", "diff", "--name-only", f"{base_ref}...{head_ref}", "--", "*.py"],
		check=True,
		capture_output=True,
		text=True,
	)
	files = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
	return [path for path in files if Path(path).suffix in {".py", ".pyi"}]


def resolve_ruff_runner(which=shutil.which) -> list[str]:
	"""Use the shell Ruff executable when available, else fall back to the Python module."""
	return ["ruff"] if which("ruff") else [sys.executable, "-m", "ruff"]


def build_commands(files: list[str], *, all_files: bool, ruff_prefix: list[str] | None = None) -> list[list[str]]:
	"""Build the command list for the local quality gate."""
	commands: list[list[str]] = []
	ruff_prefix = ruff_prefix or resolve_ruff_runner()
	if all_files:
		commands.append([*ruff_prefix, "check", "."])
	elif files:
		commands.append([*ruff_prefix, "check", *files])

	commands.append([sys.executable, "-m", "pytest", ARCHITECTURE_TEST, "-q"])
	return commands


def main() -> int:
	parser = argparse.ArgumentParser(description="Run local lint/test checks before pushing.")
	parser.add_argument("--base-ref", default="origin/main", help="Base git ref for changed-file diffing.")
	parser.add_argument("--head-ref", default="HEAD", help="Head git ref for changed-file diffing.")
	parser.add_argument("--all-files", action="store_true", help="Run Ruff against the whole repository.")
	args = parser.parse_args()

	files = [] if args.all_files else changed_python_files(args.base_ref, args.head_ref)
	commands = build_commands(files, all_files=args.all_files)

	for command in commands:
		print(f"Running: {' '.join(command)}")
		completed = subprocess.run(command, check=False)
		if completed.returncode != 0:
			return completed.returncode
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
