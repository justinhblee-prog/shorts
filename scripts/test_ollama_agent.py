"""Isolated safety and tool-contract tests for scripts/ollama-agent.py.

These tests use only the Python standard library. They never contact a live
Ollama service, execute a real subprocess, read credentials, or call paid APIs.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("ollama-agent.py")
SPEC = importlib.util.spec_from_file_location("ollama_agent_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ollama_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ollama_agent)


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class SafePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            ollama_agent.safe_path(self.root, "../outside.txt")

    def test_rejects_absolute_paths(self):
        with self.assertRaises(ValueError):
            ollama_agent.safe_path(self.root, str(self.root.parent / "outside.txt"))

    def test_rejects_protected_manifest_writes(self):
        with self.assertRaisesRegex(ValueError, "Protected task manifest"):
            ollama_agent.safe_path(self.root, ".devflow/tasks.json", writing=True)

    def test_rejects_secret_names_and_blocked_directories(self):
        for relative in (".env", ".env.local", "credentials.json", "secrets.json",
                         ".git/config", ".venv/pyvenv.cfg", "node_modules/pkg/index.js",
                         "__pycache__/module.pyc"):
            with self.subTest(path=relative):
                with self.assertRaises(ValueError):
                    ollama_agent.safe_path(self.root, relative)

    def test_write_file_rejects_oversized_content(self):
        with self.assertRaisesRegex(ValueError, "500 KiB limit"):
            ollama_agent.write_file(
                self.root, "too-large.txt", "x" * (ollama_agent.MAX_FILE_BYTES + 1)
            )
        self.assertFalse((self.root / "too-large.txt").exists())

    def test_read_file_rejects_oversized_file(self):
        path = self.root / "large.txt"
        path.write_bytes(b"x" * (ollama_agent.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "500 KiB limit"):
            ollama_agent.read_file(self.root, "large.txt")

    def test_write_file_creates_nested_utf8_file(self):
        result = ollama_agent.write_file(self.root, "src/nested/sample.txt", "안전한 텍스트")
        self.assertIn("Wrote src/nested/sample.txt", result)
        self.assertEqual(
            (self.root / "src/nested/sample.txt").read_text(encoding="utf-8"),
            "안전한 텍스트",
        )


class ToolContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_run_check_schema_exposes_only_documented_allowlist(self):
        run_check = next(
            item["function"] for item in ollama_agent.TOOLS
            if item["function"]["name"] == "run_check"
        )
        allowed = run_check["parameters"]["properties"]["check"]["enum"]
        self.assertEqual(
            set(allowed),
            {"devflow_validate", "git_diff_check", "python_compile"},
        )

    def test_each_allowlisted_check_uses_a_fixed_command(self):
        expected = {
            "devflow_validate": ["scripts/devflow.py", "validate"],
            "git_diff_check": ["git", "diff", "--check"],
            "python_compile": ["-m", "compileall", "-q", "scripts"],
        }
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch.object(
            ollama_agent.subprocess, "run", return_value=completed
        ) as run:
            for check, command_tail in expected.items():
                with self.subTest(check=check):
                    result = ollama_agent.run_check(self.root, check)
                    self.assertIn("exit_code=0", result)
                    actual = run.call_args.args[0]
                    if check == "devflow_validate":
                        self.assertEqual(actual[1:], command_tail)
                    elif check == "git_diff_check":
                        self.assertEqual(actual, command_tail)
                    else:
                        self.assertEqual(actual[1:], command_tail)
                    self.assertEqual(run.call_args.kwargs["cwd"], self.root)
        self.assertEqual(run.call_count, 3)

    def test_unknown_check_is_rejected_without_subprocess(self):
        with mock.patch.object(ollama_agent.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Unsupported check"):
                ollama_agent.run_check(self.root, "arbitrary_shell")
            run.assert_not_called()

    def test_unknown_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            ollama_agent.execute(self.root, "run_shell", {"command": "whoami"})

    def test_git_diff_is_read_only_and_excludes_task_manifest(self):
        completed = subprocess.CompletedProcess([], 0, stdout="diff", stderr="")
        with mock.patch.object(
            ollama_agent.subprocess, "run", return_value=completed
        ) as run:
            result = ollama_agent.execute(self.root, "git_diff", {})
        self.assertIn("diff", result)
        self.assertEqual(
            run.call_args.args[0],
            ["git", "diff", "--", ".", ":!.devflow/tasks.json"],
        )


class OllamaHTTPTests(unittest.TestCase):
    def test_chat_uses_only_the_local_ollama_endpoint(self):
        payload = {"message": {"role": "assistant", "content": "ok"}}
        with mock.patch.object(
            ollama_agent.urllib.request, "urlopen",
            return_value=FakeHTTPResponse(payload),
        ) as urlopen:
            result = ollama_agent.chat("qwen2.5-coder:7b", [
                {"role": "user", "content": "test"}
            ])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(json.loads(request.data)["model"], "qwen2.5-coder:7b")
        self.assertEqual(result["message"]["content"], "ok")

    def test_chat_reports_local_service_unavailable(self):
        with mock.patch.object(
            ollama_agent.urllib.request, "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaisesRegex(RuntimeError, "local Ollama"):
                ollama_agent.chat("qwen2.5-coder:7b", [
                    {"role": "user", "content": "test"}
                ])


class TextToolCallFallbackTests(unittest.TestCase):
    def test_parses_qwen_json_code_fence(self):
        content = (
            "Use this tool:\n```json\n"
            '{"name":"list_files","arguments":{"path":"scripts"}}\n```'
        )
        calls = ollama_agent.parse_text_tool_call(content)
        self.assertEqual(calls[0]["function"]["name"], "list_files")
        self.assertEqual(calls[0]["function"]["arguments"], {"path": "scripts"})

    def test_ignores_unknown_tool_names(self):
        calls = ollama_agent.parse_text_tool_call(
            '{"name":"run_shell","arguments":{"command":"whoami"}}'
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
