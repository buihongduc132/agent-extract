from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


@pytest.fixture
def run_cli():
    def _run(input_text: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        return subprocess.run(
            [sys.executable, "-m", "agent_extract.cli", *args],
            input=input_text,
            text=True,
            capture_output=True,
            env=env,
            cwd=PROJECT_ROOT,
        )

    return _run


def fixture_text(*parts: str) -> str:
    return (PROJECT_ROOT / "tests" / "fixtures").joinpath(*parts).read_text()
