#!/usr/bin/env python3
"""Real local Ollama tool-call protocol diagnostic; no files are modified."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import importlib.util

MODULE_PATH = Path(__file__).with_name("ollama-agent.py")
SPEC = importlib.util.spec_from_file_location("ollama_agent_protocol", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    system = (
        "You are testing tool calling. You MUST call the list_files tool exactly once "
        "with path set to scripts. Do not answer in natural language. Do not call any "
        "other tool. The tool call is the entire task."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Call list_files with {\"path\":\"scripts\"} now."},
    ]
    try:
        response = agent.chat(args.model, messages)
    except Exception as exc:
        print(f"FAIL: local Ollama request failed: {exc}", file=sys.stderr)
        return 2

    message = response.get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        calls = agent.parse_text_tool_call(str(message.get("content", "")))
    details = {
        "model": args.model,
        "done_reason": response.get("done_reason"),
        "eval_count": response.get("eval_count"),
        "content_chars": len(str(message.get("content", ""))),
        "native_tool_calls": len(message.get("tool_calls") or []),
        "parsed_tool_calls": len(calls),
    }
    print("[OLLAMA TOOL DIAGNOSTIC] " + json.dumps(details, ensure_ascii=False))
    if not calls:
        print(
            "FAIL: model returned no usable tool call. Native tool calling and the "
            "JSON-text fallback are both unavailable for this prompt.",
            file=sys.stderr,
        )
        return 3

    fn = calls[0].get("function") or {}
    name = fn.get("name")
    arguments = fn.get("arguments") or {}
    if name != "list_files" or arguments.get("path") != "scripts":
        print(
            "FAIL: model returned an unexpected tool request: "
            + json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 4

    try:
        output = agent.execute(root, name, arguments)
    except Exception as exc:
        print(f"FAIL: tool execution failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5
    if "ollama-agent.py" not in output:
        print("FAIL: list_files tool result did not include ollama-agent.py.", file=sys.stderr)
        return 6

    print("PASS: local model generated a valid list_files tool call and the isolated tool executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
