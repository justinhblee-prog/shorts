#!/usr/bin/env python3
"""Local Ollama coding agent for isolated DevFlow worktrees; stdlib only."""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, urllib.error, urllib.request
from pathlib import Path
from typing import Any

API = "http://127.0.0.1:11434/api/chat"
MAX_FILE_BYTES = 512_000
MAX_TOOL_OUTPUT = 18_000
BLOCKED_PARTS = {".git", ".env", ".venv", "node_modules", "__pycache__"}
BLOCKED_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json"}
PROTECTED_FILES = {".devflow/tasks.json"}

TOOLS = [
 {"type":"function","function":{"name":"list_files","description":"List repository files under a relative directory.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":[]}}},
 {"type":"function","function":{"name":"read_file","description":"Read a UTF-8 text file.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
 {"type":"function","function":{"name":"write_file","description":"Create or replace a UTF-8 text file. Protected files cannot be changed.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"search_text","description":"Search repository text files using a regular expression.","parameters":{"type":"object","properties":{"pattern":{"type":"string"},"path":{"type":"string"}},"required":["pattern"]}}},
 {"type":"function","function":{"name":"run_check","description":"Run a predefined validation only: devflow_validate, git_diff_check, or python_compile.","parameters":{"type":"object","properties":{"check":{"type":"string","enum":["devflow_validate","git_diff_check","python_compile"]}},"required":["check"]}}},
 {"type":"function","function":{"name":"git_diff","description":"Show current working-tree diff (read-only).","parameters":{"type":"object","properties":{},"required":[]}}}
]

def safe_path(root: Path, raw: str, writing: bool=False) -> Path:
 rel=Path(raw or ".")
 if rel.is_absolute(): raise ValueError("Absolute paths are not allowed.")
 target=(root/rel).resolve()
 if target != root and root not in target.parents: raise ValueError("Path escapes assigned worktree.")
 parts=set(target.relative_to(root).parts) if target != root else set()
 if parts & BLOCKED_PARTS or target.name in BLOCKED_NAMES: raise ValueError("Access to this path is blocked.")
 if writing and target.relative_to(root).as_posix() in PROTECTED_FILES: raise ValueError("Protected task manifest cannot be modified.")
 return target

def clip(s: str) -> str:
 return s if len(s)<=MAX_TOOL_OUTPUT else s[:MAX_TOOL_OUTPUT]+"\n...[truncated]"

def list_files(root: Path, path: str=".") -> str:
 base=safe_path(root,path)
 if not base.is_dir(): raise ValueError("Directory does not exist.")
 rows=[]
 for p in sorted(base.rglob("*")):
  if p.is_file():
   rel=p.relative_to(root)
   if set(rel.parts)&BLOCKED_PARTS or p.name in BLOCKED_NAMES: continue
   rows.append(rel.as_posix())
   if len(rows)>=500: rows.append("...[limit 500]"); break
 return "\n".join(rows) or "(no files)"

def read_file(root: Path,path: str) -> str:
 p=safe_path(root,path)
 if not p.is_file(): raise ValueError("File does not exist.")
 if p.stat().st_size>MAX_FILE_BYTES: raise ValueError("File exceeds 500 KiB limit.")
 try: return clip(p.read_text(encoding="utf-8"))
 except UnicodeDecodeError as e: raise ValueError("Only UTF-8 text files can be read.") from e

def write_file(root: Path,path: str,content: str) -> str:
 p=safe_path(root,path,True)
 if len(content.encode("utf-8"))>MAX_FILE_BYTES: raise ValueError("File exceeds 500 KiB limit.")
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(content,encoding="utf-8",newline="\n")
 return f"Wrote {p.relative_to(root).as_posix()} ({len(content.encode('utf-8'))} bytes)."

def search_text(root: Path,pattern: str,path: str=".") -> str:
 base=safe_path(root,path); rx=re.compile(pattern,re.IGNORECASE); hits=[]
 files=[base] if base.is_file() else (p for p in base.rglob("*") if p.is_file())
 for p in files:
  rel=p.relative_to(root)
  if set(rel.parts)&BLOCKED_PARTS or p.name in BLOCKED_NAMES or p.stat().st_size>MAX_FILE_BYTES: continue
  try:
   for n,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
    if rx.search(line):
     hits.append(f"{rel.as_posix()}:{n}: {line[:300]}")
     if len(hits)>=100: return "\n".join(hits)+"\n...[limit 100]"
  except (UnicodeDecodeError,OSError): continue
 return "\n".join(hits) or "(no matches)"

def run_check(root: Path,check: str) -> str:
 if check=="devflow_validate": cmd=[sys.executable,"scripts/devflow.py","validate"]
 elif check=="git_diff_check": cmd=["git","diff","--check"]
 elif check=="python_compile": cmd=[sys.executable,"-m","compileall","-q","scripts"]
 else: raise ValueError("Unsupported check.")
 r=subprocess.run(cmd,cwd=root,capture_output=True,text=True,timeout=180)
 return f"exit_code={r.returncode}\n{clip((r.stdout or '')+(r.stderr or ''))}"

def execute(root: Path,name: str,a: dict[str,Any]) -> str:
 if name=="list_files": return list_files(root,str(a.get("path",".")))
 if name=="read_file": return read_file(root,str(a["path"]))
 if name=="write_file": return write_file(root,str(a["path"]),str(a["content"]))
 if name=="search_text": return search_text(root,str(a["pattern"]),str(a.get("path",".")))
 if name=="run_check": return run_check(root,str(a["check"]))
 if name=="git_diff":
  r=subprocess.run(["git","diff","--",".",":!.devflow/tasks.json"],cwd=root,capture_output=True,text=True,timeout=30)
  return f"exit_code={r.returncode}\n{clip(r.stdout+r.stderr)}"
 raise ValueError(f"Unknown tool: {name}")

def chat(model: str,messages: list[dict[str,Any]]) -> dict[str,Any]:
 body=json.dumps({"model":model,"messages":messages,"tools":TOOLS,"stream":False,"options":{"temperature":0.1,"num_ctx":16384}}).encode()
 req=urllib.request.Request(API,data=body,headers={"Content-Type":"application/json"})
 try:
  with urllib.request.urlopen(req,timeout=300) as response: return json.loads(response.read().decode())
 except urllib.error.URLError as e: raise RuntimeError(f"Cannot reach local Ollama at {API}. Start Ollama and check the installed model. Details: {e}") from e

def parse_text_tool_call(content: str) -> list[dict[str, Any]]:
 """Accept Qwen's JSON-in-text tool-call fallback as well as native tool_calls."""
 if not content:
  return []
 candidates=[]
 for match in re.finditer(r"\x60\x60\x60(?:json)?\s*(\{.*?\})\s*\x60\x60\x60", content, re.IGNORECASE | re.DOTALL):
  candidates.append(match.group(1))
 if not candidates:
  decoder=json.JSONDecoder()
  for i,ch in enumerate(content):
   if ch=="{":
    try:
     value,end=decoder.raw_decode(content[i:])
     if isinstance(value,dict) and "name" in value and "arguments" in value:
      candidates.append(content[i:i+end]);break
    except json.JSONDecodeError:
     continue
 for raw in candidates:
  try: value=json.loads(raw)
  except json.JSONDecodeError: continue
  if isinstance(value,dict) and value.get("name") in {"list_files","read_file","write_file","search_text","run_check","git_diff"} and isinstance(value.get("arguments",{}),dict):
   return [{"function":{"name":value["name"],"arguments":value.get("arguments",{})}}]
 return []

def main() -> int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--prompt-file",required=True)
 ap.add_argument("--model",default=os.environ.get("DEVFLOW_OLLAMA_MODEL","qwen2.5-coder:7b"))
 ap.add_argument("--max-turns",type=int,default=32)
 args=ap.parse_args()
 root=Path.cwd().resolve(); prompt_path=Path(args.prompt_file).resolve()
 if not prompt_path.is_file(): print(f"Prompt file not found: {prompt_path}",file=sys.stderr); return 2
 prompt=prompt_path.read_text(encoding="utf-8-sig")
 system=("You are a careful coding agent in one assigned Git worktree. Inspect, implement, and validate the task using tools. "
 "Never modify .devflow/tasks.json, credentials, secrets, or files outside this worktree. "
 "Do not use network access, external APIs, arbitrary shell commands, deployment, or publishing. "
 "Make focused changes, inspect your diff, and run applicable predefined checks. "
 "If blocked, explain precisely; never fabricate success. "
 "If native tool calling is unavailable, request tools by returning exactly one JSON object with keys name and arguments, without Markdown.")
 messages=[{"role":"system","content":system},{"role":"user","content":f"Assigned task:\n{prompt}\n\nRepository root: {root}\nModel: {args.model}\nDo not claim checks passed unless run_check confirms exit_code=0."}]
 empty_responses=0
 for _ in range(args.max_turns):
  msg=(chat(args.model,messages).get("message") or {})
  calls=msg.get("tool_calls") or []
  if not calls:
   content=str(msg.get("content", ""))
   calls=parse_text_tool_call(content)
   if not calls:
    if not content.strip():
     empty_responses += 1
     if empty_responses <= 2:
      messages.append({"role":"assistant","content":""})
      messages.append({"role":"user","content":"Your previous response was empty. Continue the assigned implementation now. Use one available tool. If tool calling is unavailable, output exactly one JSON object such as {\\\"name\\\":\\\"list_files\\\",\\\"arguments\\\":{\\\"path\\\":\\\".\\\"}} with no Markdown."})
      continue
     print("Agent repeatedly returned an empty response; refusing to report success.",file=sys.stderr); return 4
    messages.append(msg)
    print(content); return 0
   # Normalize JSON-in-text calls to Ollama's native tool-call message shape.
   msg={"role":"assistant","content":"","tool_calls":calls}
  messages.append(msg)
  for call in calls:
   fn=call.get("function") or {}; name=fn.get("name",""); arguments=fn.get("arguments") or {}
   try: result=execute(root,name,arguments)
   except Exception as e: result=f"TOOL_ERROR: {type(e).__name__}: {e}"
   messages.append({"role":"tool","name":name,"content":clip(str(result))})
 print(f"Agent stopped at configured limit of {args.max_turns} turns.",file=sys.stderr); return 3

if __name__=="__main__":
 try: raise SystemExit(main())
 except Exception as e: print(f"Ollama Agent error: {e}",file=sys.stderr); raise SystemExit(1)
