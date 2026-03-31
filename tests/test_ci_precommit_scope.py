"""Tests for CI pre-commit scope selection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/ci/run_precommit_scope.py")
PRE_COMMIT_CONFIG_PATH = Path(".pre-commit-config.yaml")


def _load_module():
	spec = importlib.util.spec_from_file_location("run_precommit_scope", SCRIPT_PATH)
	module = importlib.util.module_from_spec(spec)
	assert spec is not None and spec.loader is not None
	spec.loader.exec_module(module)
	return module


def test_pull_request_uses_base_and_head_refs():
	module = _load_module()

	command = module.build_precommit_command(
		{
			"GITHUB_EVENT_NAME": "pull_request",
			"PR_BASE_SHA": "base123",
			"PR_HEAD_SHA": "head456",
		}
	)

	assert command == [
		sys.executable,
		"-m",
		"pre_commit",
		"run",
		"--from-ref",
		"base123",
		"--to-ref",
		"head456",
		"--show-diff-on-failure",
		"--color",
		"always",
	]


def test_push_uses_before_and_after_refs():
	module = _load_module()

	command = module.build_precommit_command(
		{
			"GITHUB_EVENT_NAME": "push",
			"PUSH_BEFORE_SHA": "before123",
			"GITHUB_SHA": "after456",
		}
	)

	assert command == [
		sys.executable,
		"-m",
		"pre_commit",
		"run",
		"--from-ref",
		"before123",
		"--to-ref",
		"after456",
		"--show-diff-on-failure",
		"--color",
		"always",
	]


def test_fallback_uses_all_files_when_refs_missing():
	module = _load_module()

	command = module.build_precommit_command({"GITHUB_EVENT_NAME": "workflow_dispatch"})

	assert command == [
		sys.executable,
		"-m",
		"pre_commit",
		"run",
		"--all-files",
		"--show-diff-on-failure",
		"--color",
		"always",
	]


def test_ruff_hook_is_diff_scoped():
	config_text = PRE_COMMIT_CONFIG_PATH.read_text(encoding="utf-8")

	assert "id: ruff-check" in config_text
	assert "entry: ruff check ." not in config_text
	assert "entry: ruff check\n" in config_text

	ruff_section = config_text.split("id: ruff-check", maxsplit=1)[1].split("id: architecture-boundaries", maxsplit=1)[0]
	assert "pass_filenames: false" not in ruff_section
