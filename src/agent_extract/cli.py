from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Any


GUIDANCE = """Your input did not contain valid JSONL.

Correct usage:
  ocxo run --format json "<prompt>" | agent-extract
  codex exec --json "<prompt>" | agent-extract
"""


@dataclass
class Options:
    subcommand: str
    show_session: bool
    show_duration: bool
    show_agent: bool
    show_model: bool
    output_json: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-extract",
        description="Extract text and metadata from OpenCode or Codex JSONL output.",
        add_help=False,
    )
    parser.add_argument("subcommand", nargs="?", default="final-text")
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--no-duration", action="store_true")
    parser.add_argument("--no-agent", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-h", "--help", action="help")
    return parser


def parse_args(argv: list[str]) -> Options:
    ns = build_parser().parse_args(argv)
    if ns.subcommand not in {"final-text", "last-text", "before-finish", "tools"}:
        print(f"Error: Unknown subcommand: {ns.subcommand}", file=sys.stderr)
        build_parser().print_help(sys.stderr)
        raise SystemExit(1)
    return Options(
        subcommand=ns.subcommand,
        show_session=not ns.no_session,
        show_duration=not ns.no_duration,
        show_agent=not ns.no_agent,
        show_model=not ns.no_model,
        output_json=ns.json,
    )


def format_duration(ms: int) -> str:
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    if hours > 0:
        return f"{hours}h {minutes % 60}m {seconds % 60}s"
    if minutes > 0:
        return f"{minutes}m {seconds % 60}s"
    if seconds > 0:
        return f"{seconds}s"
    return f"{ms}ms"


def load_json_lines(raw_input: str) -> tuple[list[dict[str, Any]], str]:
    json_objects: list[dict[str, Any]] = []
    non_json_lines: list[str] = []
    for line in raw_input.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            non_json_lines.append(line)
            continue
        if isinstance(parsed, dict):
            json_objects.append(parsed)
        else:
            non_json_lines.append(line)
    return json_objects, "\n".join(non_json_lines)


def detect_provider(events: list[dict[str, Any]]) -> str:
    for event in events:
        event_type = event.get("type")
        if "sessionID" in event or (
            event_type in {"text", "step_finish", "tool_use", "tool_result", "error"} and "part" in event
        ):
            return "opencode"
        item = event.get("item")
        if "thread_id" in event or event_type in {"thread.started", "turn.started", "turn.completed"}:
            return "codex"
        if isinstance(item, dict) and item.get("type") in {"agent_message", "command_execution", "error"}:
            return "codex"
    return "unknown"


def extract_opencode_error(event: dict[str, Any]) -> str:
    error = event.get("error", {})
    data = error.get("data", {}) if isinstance(error, dict) else {}
    name = error.get("name", "Unknown") if isinstance(error, dict) else "Unknown"
    message = data.get("message", "No message") if isinstance(data, dict) else "No message"
    status = data.get("statusCode", "N/A") if isinstance(data, dict) else "N/A"
    return f"Error: {name}\nMessage: {message}\nStatus: {status}"


def get_opencode_metadata(session_id: str) -> tuple[str, str]:
    db_path = os.environ.get("OPENCODE_DB_PATH", os.path.expanduser("~/.local/share/opencode/opencode.db"))
    if not session_id or not os.path.exists(db_path):
        return "", ""
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(
                "SELECT data FROM message WHERE session_id = ? ORDER BY time_created ASC LIMIT 1",
                (session_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return "", ""
        payload = json.loads(row[0])
        agent = payload.get("agent", "") if isinstance(payload, dict) else ""
        model = ""
        if isinstance(payload, dict):
            model_info = payload.get("model", {})
            if isinstance(model_info, dict):
                provider = model_info.get("providerID", "unknown")
                model_id = model_info.get("modelID", "unknown")
                model = f"{provider}/{model_id}"
        return agent, model
    except Exception:
        return "", ""


def summarize_tools(tool_events: list[dict[str, Any]]) -> dict[str, Any]:
    names = [event["name"] for event in tool_events]
    counter = Counter(names)
    return {
        "tools": sorted(counter),
        "files_read": [path for event in tool_events for path in event.get("files_read", [])],
        "files_written": [path for event in tool_events for path in event.get("files_written", [])],
        "commands": [command for event in tool_events for command in event.get("commands", [])],
        "total_calls": len(tool_events),
        "by_tool": [{"name": name, "count": counter[name]} for name in sorted(counter)],
    }


def render_tools(payload: dict[str, Any], options: Options, session_id: str, duration_ms: int, agent: str, model: str) -> str:
    if options.output_json:
        return json.dumps(payload)

    lines: list[str] = []
    lines.extend(render_header(options, session_id, duration_ms, agent, model))
    tools = ", ".join(payload["tools"])
    lines.extend(
        [
            f"Tools Used: {tools}" if tools else "Tools Used: ",
            "",
            f"Total Tool Calls: {payload['total_calls']}",
            "",
            "Calls by Tool:",
        ]
    )
    if payload["by_tool"]:
        lines.extend(f"  {item['name']}: {item['count']}" for item in payload["by_tool"])
    else:
        lines.append("  (none)")
    lines.extend(["", "Files Read:"])
    lines.extend([f"  {path}" for path in payload["files_read"]] or ["  (none)"])
    lines.extend(["", "Files Written/Edited:"])
    lines.extend([f"  {path}" for path in payload["files_written"]] or ["  (none)"])
    lines.extend(["", "Commands Run:"])
    lines.extend([f"  {command}" for command in payload["commands"]] or ["  (none)"])
    return "\n".join(lines)


def render_header(options: Options, session_id: str, duration_ms: int, agent: str, model: str) -> list[str]:
    lines: list[str] = []
    if options.show_session and session_id:
        lines.append(f"Session: {session_id}")
    if options.show_agent and agent:
        lines.append(f"Agent: {agent}")
    if options.show_model and model:
        lines.append(f"Model: {model}")
    if options.show_duration and duration_ms > 0:
        lines.append(f"Duration: {format_duration(duration_ms)}")
    if lines:
        lines.append("---")
    return lines


def render_text(text: str, options: Options, session_id: str, duration_ms: int, agent: str, model: str) -> str:
    lines = render_header(options, session_id, duration_ms, agent, model)
    lines.append(text)
    return "\n".join(lines)


def parse_opencode(events: list[dict[str, Any]], options: Options) -> tuple[int, str, str]:
    first = events[0]
    if first.get("type") == "error":
        session = first.get("sessionID", "")
        header = render_header(options, session, 0, "", "")
        message = extract_opencode_error(first)
        return 1, "", "\n".join(header + [message])

    session_id = next((event.get("sessionID", "") for event in events if event.get("sessionID")), "")
    timestamps = [event.get("timestamp") for event in events if isinstance(event.get("timestamp"), int)]
    duration_ms = (timestamps[-1] - timestamps[0]) if timestamps else 0
    agent, model = get_opencode_metadata(session_id)

    if options.subcommand == "last-text":
        texts = [event.get("part", {}).get("text") for event in events if event.get("type") == "text"]
        text = texts[-1] if texts else ""
        if not text:
            return 1, "", f"Error: No text content found for subcommand '{options.subcommand}'"
        return 0, render_text(text, options, session_id, duration_ms, agent, model), ""

    if options.subcommand == "before-finish":
        finishes = [event for event in events if event.get("type") == "step_finish"]
        if not finishes:
            return 1, "", f"Error: No text content found for subcommand '{options.subcommand}'"
        message_id = finishes[-1].get("part", {}).get("messageID")
        texts = [
            event.get("part", {}).get("text")
            for event in events
            if event.get("type") == "text" and event.get("part", {}).get("messageID") == message_id
        ]
        text = texts[-1] if texts else ""
        if not text:
            return 1, "", f"Error: No text content found for subcommand '{options.subcommand}'"
        return 0, render_text(text, options, session_id, duration_ms, agent, model), ""

    if options.subcommand == "final-text":
        grouped: dict[str, dict[str, Any]] = {}
        for event in events:
            part = event.get("part", {})
            message_id = part.get("messageID")
            if not message_id:
                continue
            entry = grouped.setdefault(message_id, {"finished": False, "texts": []})
            if event.get("type") == "step_finish":
                entry["finished"] = True
            if event.get("type") == "text":
                text = part.get("text")
                if text:
                    entry["texts"].append(text)
        finished_ids = [message_id for message_id, entry in grouped.items() if entry["finished"] and entry["texts"]]
        if not finished_ids:
            return 1, "", f"Error: No text content found for subcommand '{options.subcommand}'"
        text = grouped[finished_ids[-1]]["texts"][-1]
        return 0, render_text(text, options, session_id, duration_ms, agent, model), ""

    tool_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part", {})
        tool_name = part.get("toolName")
        input_data = part.get("input", {})
        tool_event = {"name": tool_name, "files_read": [], "files_written": [], "commands": []}
        if tool_name == "read":
            path = input_data.get("filePath") or input_data.get("file_path")
            if path:
                tool_event["files_read"].append(path)
        if tool_name in {"write", "edit"}:
            path = input_data.get("filePath") or input_data.get("file_path")
            if path:
                tool_event["files_written"].append(path)
        if tool_name == "bash":
            command = input_data.get("command")
            if command:
                tool_event["commands"].append(command)
        tool_events.append(tool_event)
    payload = summarize_tools(tool_events)
    return 0, render_tools(payload, options, session_id, duration_ms, agent, model), ""


def parse_codex(events: list[dict[str, Any]], options: Options) -> tuple[int, str, str]:
    session_id = next((event.get("thread_id", "") for event in events if event.get("thread_id")), "")
    duration_ms = 0
    agent = ""
    model = ""

    agent_messages = [
        event.get("item", {}).get("text")
        for event in events
        if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"
    ]
    final_text = agent_messages[-1] if agent_messages else ""

    if options.subcommand in {"final-text", "last-text", "before-finish"}:
        if not final_text:
            return 1, "", f"Error: No text content found for subcommand '{options.subcommand}'"
        return 0, render_text(final_text, options, session_id, duration_ms, agent, model), ""

    tool_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item", {})
        if item.get("type") != "command_execution":
            continue
        command = item.get("command")
        tool_events.append(
            {
                "name": "command_execution",
                "files_read": [],
                "files_written": [],
                "commands": [command] if command else [],
            }
        )
    payload = summarize_tools(tool_events)
    return 0, render_tools(payload, options, session_id, duration_ms, agent, model), ""


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv or sys.argv[1:])
    raw_input = sys.stdin.read()
    if not raw_input:
        print("Error: No input provided", file=sys.stderr)
        return 1

    events, non_json = load_json_lines(raw_input)
    if not events:
        if non_json:
            print(non_json, file=sys.stderr)
        print(GUIDANCE.rstrip(), file=sys.stderr)
        return 1

    provider = detect_provider(events)
    if provider == "unknown":
        print("Unsupported JSON format", file=sys.stderr)
        return 1

    if provider == "opencode":
        code, stdout, stderr = parse_opencode(events, options)
    else:
        code, stdout, stderr = parse_codex(events, options)

    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
