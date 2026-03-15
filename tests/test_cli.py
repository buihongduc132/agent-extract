from __future__ import annotations

import json
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixture_text(*parts: str) -> str:
    return FIXTURES_DIR.joinpath(*parts).read_text()


def test_defaults_to_final_text_for_opencode_stream(run_cli):
    result = run_cli(fixture_text("opencode", "final_text.jsonl"))
    assert result.returncode == 0
    assert result.stdout.strip().endswith("Final OpenCode text")


def test_preserves_opencode_last_text_behavior(run_cli):
    result = run_cli(fixture_text("opencode", "last_text.jsonl"), "last-text", "--no-session", "--no-duration")
    assert result.returncode == 0
    assert result.stdout.strip() == "Last OpenCode text"


def test_preserves_opencode_before_finish_behavior(run_cli):
    result = run_cli(fixture_text("opencode", "before_finish.jsonl"), "before-finish", "--no-session", "--no-duration")
    assert result.returncode == 0
    assert result.stdout.strip() == "Before finish OpenCode text"


def test_preserves_opencode_tools_summary_json_shape(run_cli):
    result = run_cli(fixture_text("opencode", "tools.jsonl"), "tools", "--json", "--no-session", "--no-duration")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["tools"] == ["bash", "edit", "read"]
    assert payload["files_read"] == ["/tmp/read-a.md", "/tmp/read-b.md"]
    assert payload["files_written"] == ["/tmp/write-c.md"]
    assert payload["commands"] == ["ls -la"]
    assert payload["total_calls"] == 4
    assert payload["by_tool"] == [
        {"name": "bash", "count": 1},
        {"name": "edit", "count": 1},
        {"name": "read", "count": 2},
    ]


def test_codex_jsonl_final_text_is_extracted(run_cli):
    result = run_cli(fixture_text("codex", "final_text.jsonl"))
    assert result.returncode == 0
    assert result.stdout.strip().endswith("done")


def test_codex_jsonl_last_text_is_extracted(run_cli):
    result = run_cli(fixture_text("codex", "final_text.jsonl"), "last-text", "--no-session", "--no-duration")
    assert result.returncode == 0
    assert result.stdout.strip() == "done"


def test_codex_jsonl_before_finish_text_is_extracted(run_cli):
    result = run_cli(fixture_text("codex", "final_text.jsonl"), "before-finish", "--no-session", "--no-duration")
    assert result.returncode == 0
    assert result.stdout.strip() == "done"


def test_codex_jsonl_tools_are_summarized_to_common_schema(run_cli):
    result = run_cli(fixture_text("codex", "tools.jsonl"), "tools", "--json", "--no-session", "--no-duration")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["tools"] == ["command_execution"]
    assert payload["files_read"] == []
    assert payload["files_written"] == []
    assert payload["commands"] == ["/usr/bin/zsh -lc pwd"]
    assert payload["total_calls"] == 1
    assert payload["by_tool"] == [{"name": "command_execution", "count": 1}]


def test_codex_structured_output_final_json_text_is_returned_verbatim(run_cli):
    result = run_cli(fixture_text("codex", "structured_output.jsonl"), "final-text", "--no-session", "--no-duration")
    assert result.returncode == 0
    assert result.stdout.strip() == '{"answer":"hi"}'


def test_auto_detects_opencode_vs_codex_without_flag(run_cli):
    opencode_result = run_cli(fixture_text("opencode", "final_text.jsonl"), "final-text", "--no-session", "--no-duration")
    codex_result = run_cli(fixture_text("codex", "final_text.jsonl"), "final-text", "--no-session", "--no-duration")
    assert opencode_result.returncode == 0
    assert codex_result.returncode == 0
    assert opencode_result.stdout.strip() == "Final OpenCode text"
    assert codex_result.stdout.strip() == "done"


def test_unknown_json_format_fails_with_clear_error(run_cli):
    result = run_cli('{"hello":"world"}\n')
    assert result.returncode == 1
    assert "Unsupported JSON format" in result.stderr


def test_non_json_input_mentions_both_ocxo_and_codex_json_modes(run_cli):
    result = run_cli("plain text only\n")
    assert result.returncode == 1
    assert "ocxo run --format json" in result.stderr
    assert "codex exec --json" in result.stderr
