"""Validate release metadata and generate draft release notes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


VERSION_PATH = Path("VERSION")
CHANGELOG_PATH = Path("CHANGELOG.md")
FRONTEND_PACKAGE_PATH = Path("frontend/package.json")
DEFAULT_OUTPUT_ROOT = Path("output/mock-releases")


def read_version(root: Path) -> str:
	"""Read the canonical repo version."""
	return (root / VERSION_PATH).read_text(encoding="utf-8").strip()


def read_frontend_version(root: Path) -> str:
	"""Read the frontend package version."""
	return json.loads((root / FRONTEND_PACKAGE_PATH).read_text(encoding="utf-8"))["version"]


def extract_version_section(changelog_text: str, version: str) -> str:
	"""Extract the markdown body for a given version section."""
	lines = changelog_text.splitlines()
	target_heading = f"## [{version}]"
	start_index: int | None = None
	for index, line in enumerate(lines):
		if line.startswith(target_heading):
			start_index = index + 1
			break
	if start_index is None:
		raise ValueError(f"CHANGELOG.md does not contain section for version {version}")

	end_index = len(lines)
	for index in range(start_index, len(lines)):
		if lines[index].startswith("## ["):
			end_index = index
			break

	section_body = "\n".join(lines[start_index:end_index]).strip()
	if not section_body:
		raise ValueError(f"CHANGELOG section for version {version} is empty")
	return section_body


def validate_release_metadata(root: Path) -> list[str]:
	"""Validate version/changelog/release metadata consistency."""
	errors: list[str] = []
	required_files = [
		VERSION_PATH,
		CHANGELOG_PATH,
		FRONTEND_PACKAGE_PATH,
		Path(".github/release.yml"),
		Path("SECURITY.md"),
		Path("docs/reference/release-process.md"),
	]
	for path in required_files:
		if not (root / path).exists():
			errors.append(f"Missing required file: {path}")

	if errors:
		return errors

	version = read_version(root)
	frontend_version = read_frontend_version(root)
	if frontend_version != version:
		errors.append(
			f"frontend/package.json version {frontend_version} does not match VERSION {version}"
		)

	changelog_text = (root / CHANGELOG_PATH).read_text(encoding="utf-8")
	if "## [Unreleased]" not in changelog_text:
		errors.append("CHANGELOG.md is missing an [Unreleased] section")
	if f"## [{version}]" not in changelog_text:
		errors.append(f"CHANGELOG.md is missing a [{version}] section")
	return errors


def git_worktree_is_clean(root: Path) -> bool:
	"""Return whether the git worktree is clean."""
	completed = subprocess.run(
		["git", "status", "--porcelain"],
		cwd=root,
		check=True,
		capture_output=True,
		text=True,
	)
	return completed.stdout.strip() == ""


def write_release_notes(*, version: str, section_body: str, output_root: Path) -> Path:
	"""Write a draft release-notes artifact."""
	output_dir = output_root / f"v{version}"
	output_dir.mkdir(parents=True, exist_ok=True)
	output_path = output_dir / "release-notes.md"
	output_path.write_text(
		f"# Alpha Pod v{version}\n\n{section_body.strip()}\n",
		encoding="utf-8",
	)
	return output_path


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Validate repo release metadata and generate draft release notes."
	)
	parser.add_argument("--root", default=".", help="Repository root to validate.")
	parser.add_argument(
		"--output-root",
		default=str(DEFAULT_OUTPUT_ROOT),
		help="Directory for generated mock release artifacts.",
	)
	parser.add_argument(
		"--check-only",
		action="store_true",
		help="Validate release metadata without generating files.",
	)
	args = parser.parse_args()

	root = Path(args.root).resolve()
	errors = validate_release_metadata(root)
	if not git_worktree_is_clean(root):
		errors.append("Git worktree is not clean")

	if errors:
		for error in errors:
			print(f"ERROR: {error}")
		return 1

	version = read_version(root)
	changelog_text = (root / CHANGELOG_PATH).read_text(encoding="utf-8")
	section_body = extract_version_section(changelog_text, version)

	if args.check_only:
		print(f"Release metadata validated for v{version}")
		return 0

	output_path = write_release_notes(
		version=version,
		section_body=section_body,
		output_root=(root / args.output_root),
	)
	print(f"Draft release notes written to {output_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
