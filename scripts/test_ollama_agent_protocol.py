"""Offline regression tests for the local Ollama tool-call protocol."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("ollama-agent.py")
SPEC = importlib.util.spec_from_file_location("ollama_agent_protocol_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class ParseTextToolCallTests(unittest.TestCase):
    def test_parses_fenced_nested_tool_calls(self):
        response = """\`\`\`json
{
  "tool_calls": [
    {
      "function": {
        "name": "list_files",
        "arguments": {"path": "scripts"}
      }
    }
  ]
}
\`\`\`"""
        self.assertEqual(
            agent.parse_text_tool_call(response),
            [{"function": {"name": "list_files", "arguments": {"path": "scripts"}}}],
        )

    def test_parses_raw_single_tool_call(self):
        response = '{"name":"read_file","arguments":{"path":"scripts/ollama-agent.py"}}'
        self.assertEqual(
            agent.parse_text_tool_call(response),
            [{"function": {"name": "read_file", "arguments": {"path": "scripts/ollama-agent.py"}}}],
        )

    def test_parses_string_encoded_arguments(self):
        response = '{"name":"list_files","arguments":"{\\"path\\":\\"scripts\\"}"}'
        self.assertEqual(
            agent.parse_text_tool_call(response),
            [{"function": {"name": "list_files", "arguments": {"path": "scripts"}}}],
        )

    def test_rejects_unknown_tools(self):
        self.assertEqual(
            agent.parse_text_tool_call('{"name":"run_shell","arguments":{"command":"whoami"}}'),
            [],
        )

    def test_rejects_malformed_or_empty_responses(self):
        self.assertEqual(agent.parse_text_tool_call(""), [])
        self.assertEqual(agent.parse_text_tool_call("not JSON"), [])
        self.assertEqual(agent.parse_text_tool_call('{"name":"list_files","arguments":'), [])


class ScopedPatchTests(unittest.TestCase):
    def test_scoped_patch_rejects_paths_outside_task_scope(self):
        import tempfile

        prompt = "Task: add a test\nScope:\n- scripts/new_test.py\nAcceptance:\n- keep scope"
        response = {
            "message": {
                "content": json.dumps({
                    "summary": "attempted out-of-scope write",
                    "files": [{"path": "outside.txt", "content": "must not be written"}],
                })
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(agent, "chat", return_value=response):
                result = agent.scoped_json_patch(Path(directory), prompt, "qwen2.5-coder:7b")
            self.assertEqual(result, 9)
            self.assertFalse((Path(directory) / "outside.txt").exists())

    def test_scoped_patch_writes_only_declared_scope(self):
        import tempfile

        prompt = "Task: add a test\nScope:\n- scripts/new_test.py\nAcceptance:\n- keep scope"
        response = {
            "message": {
                "content": json.dumps({
                    "summary": "created scoped file",
                    "files": [{"path": "scripts/new_test.py", "content": "VALUE = 1\n"}],
                })
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(agent, "chat", return_value=response):
                result = agent.scoped_json_patch(Path(directory), prompt, "qwen2.5-coder:7b")
            self.assertEqual(result, 0)
            self.assertEqual((Path(directory) / "scripts/new_test.py").read_text(), "VALUE = 1\n")


class ChatRequestTests(unittest.TestCase):
    def test_chat_uses_local_endpoint_tools_and_no_forced_json_format(self):
        payload = {"message": {"role": "assistant", "content": "ok"}}
        with mock.patch.object(
            agent.urllib.request,
            "urlopen",
            return_value=FakeResponse(payload),
        ) as urlopen:
            result = agent.chat(
                "qwen2.5-coder:7b",
                [{"role": "user", "content": "test"}],
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(body["model"], "qwen2.5-coder:7b")
        self.assertIn("tools", body)
        self.assertNotIn("format", body)
        self.assertEqual(result["message"]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
