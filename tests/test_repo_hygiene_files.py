"""Repository hygiene file presence and configuration tests."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(".")


def _read(path: str) -> str:
	return (ROOT / path).read_text(encoding="utf-8")


def test_expected_github_hygiene_files_exist():
	required_files = [
		".github/CODEOWNERS",
		".github/ISSUE_TEMPLATE/bug_report.yml",
		".github/ISSUE_TEMPLATE/feature_request.yml",
		".github/ISSUE_TEMPLATE/config.yml",
		"CONTRIBUTING.md",
		"docs/reference/github-hardening-checklist.md",
	]

	for file_path in required_files:
		assert (ROOT / file_path).exists(), file_path


def test_ci_workflow_uses_node24_compatible_action_majors():
	workflow = _read(".github/workflows/ci.yml")

	assert "actions/checkout@v5" in workflow or "actions/checkout@v6" in workflow
	assert "actions/setup-python@v6" in workflow
	assert "name: backend-api-tests" in workflow
	assert "python -m pytest tests/test_api_contracts.py -q" in workflow


def test_pyproject_has_explicit_ruff_configuration():
	pyproject = _read("pyproject.toml")

	assert "[tool.ruff]" in pyproject
	assert 'target-version = "py311"' in pyproject
	assert "force-exclude = true" in pyproject
	assert "[tool.ruff.lint]" in pyproject
	assert 'select = ["E", "F"]' in pyproject
	assert 'ignore = ["E501"]' in pyproject
	assert "[tool.ruff.lint.per-file-ignores]" in pyproject
	assert '"scripts/create_ibm_review.py" = ["E402", "E701", "E702"]' in pyproject


def test_gitignore_covers_local_agent_and_ruff_artifacts():
	gitignore = _read(".gitignore")

	for expected in (".ruff_cache/", ".codex/", ".gemini/", ".tmp-tests/"):
		assert expected in gitignore


def test_precommit_has_standard_text_and_merge_safety_hooks():
	config = _read(".pre-commit-config.yaml")

	assert "repo: https://github.com/pre-commit/pre-commit-hooks" in config
	for hook_id in (
		"id: check-merge-conflict",
		"id: end-of-file-fixer",
		"id: trailing-whitespace",
		"id: check-yaml",
	):
		assert hook_id in config
