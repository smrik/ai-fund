"""Tests for repo release metadata and mock release preparation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4


ROOT = Path(".")
SCRIPT_PATH = Path("scripts/release/prepare_mock_release.py")
SCRATCH_ROOT = ROOT / ".tmp-tests" / "release-readiness"


def _read(path: str) -> str:
	return (ROOT / path).read_text(encoding="utf-8")


def _load_module():
	spec = importlib.util.spec_from_file_location("prepare_mock_release", SCRIPT_PATH)
	module = importlib.util.module_from_spec(spec)
	assert spec is not None and spec.loader is not None
	spec.loader.exec_module(module)
	return module


def _scratch_dir(name: str) -> Path:
	path = SCRATCH_ROOT / f"{name}-{uuid4().hex}"
	path.mkdir(parents=True, exist_ok=True)
	return path


def test_release_metadata_files_exist():
	required_files = [
		"VERSION",
		"CHANGELOG.md",
		".github/release.yml",
		"SECURITY.md",
		"docs/reference/release-process.md",
		"docs/plans/active/2026-04-01-internal-release-readiness-and-mock-publish.md",
	]

	for file_path in required_files:
		assert (ROOT / file_path).exists(), file_path


def test_frontend_version_matches_repo_version():
	version = _read("VERSION").strip()
	package_json = json.loads(_read("frontend/package.json"))

	assert package_json["version"] == version


def test_changelog_contains_unreleased_and_current_version_heading():
	version = _read("VERSION").strip()
	changelog = _read("CHANGELOG.md")

	assert "## [Unreleased]" in changelog
	assert f"## [{version}]" in changelog


def test_ci_has_release_readiness_frontend_and_docs_jobs():
	workflow = _read(".github/workflows/ci.yml")

	for job_name in ("frontend-build:", "docs-build:", "release-readiness:"):
		assert job_name in workflow


def test_release_script_builds_release_notes_from_changelog():
	module = _load_module()
	output_root = _scratch_dir("release-notes")

	output_path = module.write_release_notes(
		version="0.1.0",
		section_body="- Example shipped change",
		output_root=output_root,
	)

	assert output_path == output_root / "v0.1.0" / "release-notes.md"
	assert output_path.exists()
	assert "# Alpha Pod v0.1.0" in output_path.read_text(encoding="utf-8")


def test_extract_version_section_returns_expected_body():
	module = _load_module()

	section = module.extract_version_section(
		"""# Changelog

## [Unreleased]

- Pending item

## [0.1.0] - 2026-04-01

- Item one
- Item two
"""
		,
		"0.1.0",
	)

	assert "- Item one" in section
	assert "- Item two" in section


def test_validate_release_metadata_reports_mismatched_frontend_version():
	module = _load_module()
	root = _scratch_dir("metadata-mismatch")
	(root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
	(root / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n## [0.1.0]\n", encoding="utf-8")
	(root / ".github").mkdir()
	(root / ".github" / "release.yml").write_text("changelog:\n  categories: []\n", encoding="utf-8")
	(root / "frontend").mkdir()
	(root / "frontend" / "package.json").write_text('{"version":"0.0.0"}', encoding="utf-8")
	(root / "docs").mkdir()
	(root / "docs" / "reference").mkdir(parents=True, exist_ok=True)
	(root / "docs" / "reference" / "release-process.md").write_text("# Release Process\n", encoding="utf-8")
	(root / "SECURITY.md").write_text("# Security Policy\n", encoding="utf-8")

	errors = module.validate_release_metadata(root)

	assert any("frontend/package.json" in error for error in errors)
