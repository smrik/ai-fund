"""Tests for the local quality-gate helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/dev/run_local_quality_gate.py")


def _load_module():
	spec = importlib.util.spec_from_file_location("run_local_quality_gate", SCRIPT_PATH)
	module = importlib.util.module_from_spec(spec)
	assert spec is not None and spec.loader is not None
	spec.loader.exec_module(module)
	return module


def test_build_commands_runs_changed_file_ruff_and_architecture_pytest():
	module = _load_module()

	commands = module.build_commands(
		["src/example.py", "tests/test_example.py"],
		all_files=False,
		ruff_prefix=["ruff"],
	)

	assert commands == [
		["ruff", "check", "src/example.py", "tests/test_example.py"],
		[sys.executable, "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"],
	]


def test_build_commands_skips_ruff_when_no_python_files_changed():
	module = _load_module()

	commands = module.build_commands([], all_files=False, ruff_prefix=["ruff"])

	assert commands == [
		[sys.executable, "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"],
	]


def test_build_commands_can_force_all_files_ruff():
	module = _load_module()

	commands = module.build_commands([], all_files=True, ruff_prefix=["ruff"])

	assert commands == [
		["ruff", "check", "."],
		[sys.executable, "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"],
	]


def test_resolve_ruff_runner_prefers_shell_executable():
	module = _load_module()

	command_prefix = module.resolve_ruff_runner(lambda name: "C:/tools/ruff.exe" if name == "ruff" else None)

	assert command_prefix == ["ruff"]


def test_resolve_ruff_runner_falls_back_to_python_module():
	module = _load_module()

	command_prefix = module.resolve_ruff_runner(lambda _name: None)

	assert command_prefix == [sys.executable, "-m", "ruff"]
