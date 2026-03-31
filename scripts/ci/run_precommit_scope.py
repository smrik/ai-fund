"""Run pre-commit against the relevant GitHub Actions diff when available."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping


COMMON_ARGS = [sys.executable, "-m", "pre_commit", "run"]
OUTPUT_ARGS = ["--show-diff-on-failure", "--color", "always"]
ZERO_SHA = "0000000000000000000000000000000000000000"


def build_precommit_command(env: Mapping[str, str]) -> list[str]:
	"""Build the most appropriate pre-commit command for the current CI event."""
	event_name = env.get("GITHUB_EVENT_NAME", "")

	if event_name == "pull_request":
		base_sha = env.get("PR_BASE_SHA", "")
		head_sha = env.get("PR_HEAD_SHA", "")
		if base_sha and head_sha:
			return [
				*COMMON_ARGS,
				"--from-ref",
				base_sha,
				"--to-ref",
				head_sha,
				*OUTPUT_ARGS,
			]

	if event_name == "push":
		before_sha = env.get("PUSH_BEFORE_SHA", "")
		head_sha = env.get("GITHUB_SHA", "")
		if before_sha and before_sha != ZERO_SHA and head_sha:
			return [
				*COMMON_ARGS,
				"--from-ref",
				before_sha,
				"--to-ref",
				head_sha,
				*OUTPUT_ARGS,
			]

	return [*COMMON_ARGS, "--all-files", *OUTPUT_ARGS]


def main() -> int:
	command = build_precommit_command(os.environ)
	print(f"Running: {' '.join(command)}")
	completed = subprocess.run(command, check=False)
	return completed.returncode


if __name__ == "__main__":
	raise SystemExit(main())
