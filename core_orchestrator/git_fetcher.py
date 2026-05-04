"""Universal Git Fetcher — platform-agnostic repository cloning and code analysis tools.

Provides five provider-agnostic tool definitions and their implementations:

  clone_repo       — git clone any HTTPS/SSH URL into an isolated sandbox directory.
  read_repo_file   — read a single file from a cloned repository.
  glob_repo        — list files matching a glob pattern inside a cloned repo.
  grep_repo        — keyword/regex search across files in a cloned repo.
  analyze_ast      — Python AST structural analysis (imports, classes, functions,
                     call sites); graceful regex fallback for other languages.

Design principles:
- Platform-neutral: delegates to the local `git` binary; works with GitHub,
  GitLab, Hugging Face, Bitbucket, and any private Git server.
- Auth: HTTPS token embedded in URL (https://token@host/path); SSH via
  GIT_SSH_COMMAND.  Tokens are **never** written to logs — scrubbed to "***".
- Sandbox enforcement: all file operations are confined to a single `repos_root`
  directory; path-traversal attempts raise ValueError before any I/O.
- Graceful degradation: AST failures fall back to regex; missing files / bad
  patterns return informative error strings (never exceptions to the LLM).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse


# ---------------------------------------------------------------------------
# Tool definitions (provider-agnostic, OpenAI function-calling format)
# ---------------------------------------------------------------------------

CLONE_REPO_TOOL: Dict[str, Any] = {
    "name": "clone_repo",
    "description": (
        "Clone a remote Git repository into the isolated sandbox workspace. "
        "Supports HTTPS and SSH URLs from any Git host (GitHub, GitLab, "
        "Hugging Face, private servers). "
        "Returns the local path where the repository was cloned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "git_url": {
                "type": "string",
                "description": (
                    "Full Git URL of the repository to clone. "
                    "HTTPS example: https://github.com/org/repo.git  "
                    "SSH example: git@github.com:org/repo.git"
                ),
            },
            "dest_name": {
                "type": "string",
                "description": (
                    "Short name for the local clone directory, e.g. 'repo-a'. "
                    "Must contain only alphanumeric characters, hyphens, and underscores."
                ),
            },
            "auth_token": {
                "type": "string",
                "description": (
                    "Optional personal access token or deploy key for private repos. "
                    "For HTTPS URLs, embedded as https://token@host/path. "
                    "For SSH URLs, provide the path to the private key file instead."
                ),
            },
            "branch": {
                "type": "string",
                "description": "Optional branch or tag name to check out (default: repository default branch).",
            },
            "depth": {
                "type": "integer",
                "description": "Optional shallow clone depth (e.g. 1 for latest commit only). Faster for large repos.",
            },
        },
        "required": ["git_url", "dest_name"],
    },
}

READ_REPO_FILE_TOOL: Dict[str, Any] = {
    "name": "read_repo_file",
    "description": (
        "Read the content of a file from a previously cloned repository. "
        "Returns the file content as a string. "
        "For large files, only the first 4000 characters are returned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "The dest_name used when cloning the repository.",
            },
            "file_path": {
                "type": "string",
                "description": "Relative path to the file within the repository (e.g. 'src/main.py').",
            },
        },
        "required": ["repo_name", "file_path"],
    },
}

GLOB_REPO_TOOL: Dict[str, Any] = {
    "name": "glob_repo",
    "description": (
        "List files matching a glob pattern inside a cloned repository. "
        "Use this to discover the project structure before reading files. "
        "Returns a JSON array of relative file paths."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "The dest_name used when cloning the repository.",
            },
            "pattern": {
                "type": "string",
                "description": (
                    "Glob pattern relative to the repo root. "
                    "Examples: '**/*.py', 'src/**/*.ts', '*.yaml', 'README*'"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of paths to return (default: 50).",
            },
        },
        "required": ["repo_name", "pattern"],
    },
}

GREP_REPO_TOOL: Dict[str, Any] = {
    "name": "grep_repo",
    "description": (
        "Search for a keyword or regex pattern across all files in a cloned repository. "
        "Returns matching lines with file path and line number context. "
        "Useful for finding class definitions, function signatures, config keys, etc."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "The dest_name used when cloning the repository.",
            },
            "pattern": {
                "type": "string",
                "description": "Search pattern (plain string or Python regex).",
            },
            "file_glob": {
                "type": "string",
                "description": "Optional file glob to restrict search (e.g. '*.py'). Default: all files.",
            },
            "max_matches": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default: 30).",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of context lines before/after each match (default: 2).",
            },
        },
        "required": ["repo_name", "pattern"],
    },
}

ANALYZE_AST_TOOL: Dict[str, Any] = {
    "name": "analyze_ast",
    "description": (
        "Perform structural analysis of a source file in a cloned repository. "
        "For Python files: extracts imports, class names, function signatures, "
        "and top-level call sites using the AST module. "
        "For other languages: performs regex-based extraction of key constructs. "
        "Returns a structured JSON summary of the file's architecture."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "The dest_name used when cloning the repository.",
            },
            "file_path": {
                "type": "string",
                "description": "Relative path to the source file within the repository.",
            },
        },
        "required": ["repo_name", "file_path"],
    },
}

WRITE_FUSION_REPORT_TOOL: Dict[str, Any] = {
    "name": "write_fusion_report",
    "description": (
        "Submit the completed cross-repository fusion architecture report. "
        "CALL THIS TOOL EXACTLY ONCE when your analysis is complete. "
        "The report will be automatically persisted as a reusable skill. "
        "Do NOT output the report as text — use this tool exclusively."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title for the fusion architecture (≤ 80 chars).",
            },
            "repos_analyzed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of repository names that were analyzed.",
            },
            "strengths_per_repo": {
                "type": "string",
                "description": "Markdown section: key strengths of each repository's architecture.",
            },
            "design_tradeoffs": {
                "type": "string",
                "description": "Markdown section: major design trade-offs identified across repositories.",
            },
            "fusion_architecture": {
                "type": "string",
                "description": (
                    "Markdown section: the recommended fusion architecture that combines "
                    "the best elements. Include code snippets where helpful."
                ),
            },
            "implementation_steps": {
                "type": "string",
                "description": "Markdown section: ordered steps to implement the fusion architecture.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Technology/domain tags for skill indexing (e.g. ['python', 'architecture', 'fastapi']).",
            },
        },
        "required": [
            "title", "repos_analyzed", "strengths_per_repo",
            "design_tradeoffs", "fusion_architecture", "implementation_steps", "tags",
        ],
    },
}


# ---------------------------------------------------------------------------
# Sandbox path helper
# ---------------------------------------------------------------------------

def _safe_repo_path(repos_root: Path, repo_name: str) -> Path:
    """Return the absolute path for a repo clone; raise ValueError on bad names."""
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", repo_name):
        raise ValueError(
            f"Invalid repo_name {repo_name!r}. "
            "Use only alphanumeric characters, hyphens, and underscores (max 64 chars)."
        )
    return repos_root / repo_name


def _safe_file_path(repo_path: Path, relative: str) -> Path:
    """Resolve a relative file path inside a repo; raise ValueError on path traversal."""
    resolved = (repo_path / relative).resolve()
    if not str(resolved).startswith(str(repo_path.resolve())):
        raise ValueError(f"Path traversal detected: {relative!r}")
    return resolved


def _scrub_token(url: str, token: str) -> str:
    """Replace token in URL with *** for logging."""
    return url.replace(token, "***") if token else url


# ---------------------------------------------------------------------------
# clone_repo
# ---------------------------------------------------------------------------

def clone_repo(
    git_url: str,
    dest_name: str,
    repos_root: Path,
    auth_token: Optional[str] = None,
    branch: Optional[str] = None,
    depth: Optional[int] = None,
    timeout: int = 300,
) -> str:
    """Clone a remote Git repository into repos_root/dest_name.

    Returns:
        Absolute path of the cloned directory (as string).

    Raises:
        ValueError: Invalid dest_name or path traversal.
        RuntimeError: git subprocess failed.
    """
    dest_path = _safe_repo_path(repos_root, dest_name)

    # If already cloned, return existing path (idempotent)
    if (dest_path / ".git").exists():
        return str(dest_path)

    # Inject token into HTTPS URL
    effective_url = git_url
    env = {**os.environ}

    if auth_token:
        parsed = urlparse(git_url)
        if parsed.scheme in ("http", "https"):
            # Embed token: https://token@host/path
            netloc_with_token = f"{auth_token}@{parsed.hostname}"
            if parsed.port:
                netloc_with_token += f":{parsed.port}"
            effective_url = urlunparse(parsed._replace(netloc=netloc_with_token))
        elif parsed.scheme == "" and git_url.startswith("git@"):
            # SSH: auth_token is interpreted as path to private key file
            env["GIT_SSH_COMMAND"] = f"ssh -i {auth_token} -o StrictHostKeyChecking=no"

    cmd = ["git", "clone", "--quiet"]
    if depth is not None and depth > 0:
        cmd += ["--depth", str(depth)]
    if branch:
        cmd += ["--branch", branch]
    cmd += [effective_url, str(dest_path)]

    safe_cmd_log = cmd.copy()
    if auth_token and effective_url != git_url:
        safe_cmd_log[safe_cmd_log.index(effective_url)] = _scrub_token(effective_url, auth_token)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        # Clean up partial clone
        if dest_path.exists():
            shutil.rmtree(dest_path, ignore_errors=True)
        raise RuntimeError(f"git clone timed out after {timeout}s for {git_url!r}")

    if result.returncode != 0:
        stderr = _scrub_token(result.stderr.strip(), auth_token or "")
        if dest_path.exists():
            shutil.rmtree(dest_path, ignore_errors=True)
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}): {stderr}"
        )

    return str(dest_path)


# ---------------------------------------------------------------------------
# read_repo_file
# ---------------------------------------------------------------------------

_MAX_FILE_CHARS = 4_000


def read_repo_file(repo_name: str, file_path: str, repos_root: Path) -> str:
    """Read a file from a cloned repository, capped at _MAX_FILE_CHARS."""
    try:
        repo_path = _safe_repo_path(repos_root, repo_name)
        full_path = _safe_file_path(repo_path, file_path)
    except ValueError as exc:
        return f"[error] {exc}"

    if not full_path.exists():
        return f"[error] File not found: {file_path}"
    if not full_path.is_file():
        return f"[error] Not a file: {file_path}"

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[error] Could not read file: {exc}"

    if len(text) > _MAX_FILE_CHARS:
        half = _MAX_FILE_CHARS // 2
        return (
            text[:half]
            + f"\n\n[… file truncated — {len(text)} chars total, showing first+last {half} …]\n\n"
            + text[-half:]
        )
    return text


# ---------------------------------------------------------------------------
# glob_repo
# ---------------------------------------------------------------------------

_MAX_GLOB_RESULTS = 50


def glob_repo(
    repo_name: str,
    pattern: str,
    repos_root: Path,
    max_results: int = _MAX_GLOB_RESULTS,
) -> str:
    """List files matching a glob pattern inside a cloned repo. Returns JSON array."""
    try:
        repo_path = _safe_repo_path(repos_root, repo_name)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if not repo_path.exists():
        return json.dumps({"error": f"Repository '{repo_name}' not found. Clone it first."})

    try:
        matches = sorted(
            str(p.relative_to(repo_path))
            for p in repo_path.glob(pattern)
            if p.is_file()
        )
    except Exception as exc:
        return json.dumps({"error": f"Glob error: {exc}"})

    if len(matches) > max_results:
        truncated = True
        matches = matches[:max_results]
    else:
        truncated = False

    return json.dumps({
        "repo": repo_name,
        "pattern": pattern,
        "count": len(matches),
        "truncated": truncated,
        "files": matches,
    }, indent=2)


# ---------------------------------------------------------------------------
# grep_repo
# ---------------------------------------------------------------------------

_MAX_GREP_MATCHES = 30
_DEFAULT_CONTEXT  = 2


def grep_repo(
    repo_name: str,
    pattern: str,
    repos_root: Path,
    file_glob: str = "**/*",
    max_matches: int = _MAX_GREP_MATCHES,
    context_lines: int = _DEFAULT_CONTEXT,
) -> str:
    """Regex/keyword search across files in a cloned repo. Returns formatted text."""
    try:
        repo_path = _safe_repo_path(repos_root, repo_name)
    except ValueError as exc:
        return f"[error] {exc}"

    if not repo_path.exists():
        return f"[error] Repository '{repo_name}' not found. Clone it first."

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"[error] Invalid regex pattern: {exc}"

    results: List[str] = []
    match_count = 0

    for fpath in sorted(repo_path.glob(file_glob)):
        if not fpath.is_file():
            continue
        # Skip binary / very large files
        try:
            raw = fpath.read_bytes()
            if b"\x00" in raw[:1024]:
                continue  # likely binary
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            continue

        lines = text.splitlines()
        rel = str(fpath.relative_to(repo_path))

        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end   = min(len(lines), i + context_lines + 1)
                ctx   = "\n".join(
                    f"  {'→' if j == i else ' '} {rel}:{j+1}  {lines[j]}"
                    for j in range(start, end)
                )
                results.append(ctx)
                match_count += 1
                if match_count >= max_matches:
                    results.append(f"\n[… search stopped at {max_matches} matches]")
                    return "\n\n".join(results)

    if not results:
        return f"[no matches] Pattern {pattern!r} not found in '{repo_name}'."
    return "\n\n".join(results)


# ---------------------------------------------------------------------------
# analyze_ast (Python-first, regex fallback)
# ---------------------------------------------------------------------------

def _analyze_python_ast(source: str, file_path: str) -> Dict[str, Any]:
    """Parse Python source with ast module and extract structural info."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"error": f"Python parse error: {exc}"}

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[str] = []
    calls: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            methods = [
                n.name for n in ast.walk(node)
                if isinstance(n, ast.FunctionDef) or isinstance(n, ast.AsyncFunctionDef)
            ]
            classes.append({"name": node.name, "bases": bases, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only top-level functions (not methods inside classes)
            functions.append(node.name)
        elif isinstance(node, ast.Call):
            try:
                call_str = ast.unparse(node.func)
                calls.append(call_str)
            except Exception:
                pass

    # Deduplicate call sites; keep top 20
    unique_calls = list(dict.fromkeys(calls))[:20]

    return {
        "language":  "python",
        "file":      file_path,
        "imports":   list(dict.fromkeys(imports)),
        "classes":   classes,
        "functions": functions,
        "call_sites": unique_calls,
    }


def _analyze_generic_regex(source: str, file_path: str, ext: str) -> Dict[str, Any]:
    """Regex-based structural extraction for non-Python files."""
    result: Dict[str, Any] = {"language": ext.lstrip(".") or "unknown", "file": file_path}

    # Imports / requires / includes
    import_patterns = [
        r'^\s*import\s+(.+)',
        r'^\s*from\s+\S+\s+import\s+(.+)',
        r'^\s*require\(["\'](.+?)["\']\)',
        r'^\s*#include\s+[<"](.+?)[>"]',
    ]
    found_imports: List[str] = []
    for pat in import_patterns:
        found_imports.extend(re.findall(pat, source, re.MULTILINE))
    result["imports"] = list(dict.fromkeys(found_imports))[:30]

    # Class / struct / interface definitions
    class_pat = re.findall(
        r'(?:class|struct|interface|type)\s+([A-Z][A-Za-z0-9_]*)',
        source,
    )
    result["types"] = list(dict.fromkeys(class_pat))[:20]

    # Function / method definitions
    func_pat = re.findall(
        r'(?:def|function|func|fn)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
        source,
    )
    result["functions"] = list(dict.fromkeys(func_pat))[:20]

    return result


def analyze_ast(repo_name: str, file_path: str, repos_root: Path) -> str:
    """Structural analysis of a source file. Returns JSON summary."""
    try:
        repo_path = _safe_repo_path(repos_root, repo_name)
        full_path = _safe_file_path(repo_path, file_path)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    if not full_path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    try:
        source = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return json.dumps({"error": f"Could not read file: {exc}"})

    ext = full_path.suffix.lower()
    if ext == ".py":
        result = _analyze_python_ast(source, file_path)
    else:
        result = _analyze_generic_regex(source, file_path, ext)

    return json.dumps(result, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool handler dispatcher (for use by FusionArchitectAgent)
# ---------------------------------------------------------------------------

def make_tool_handler(repos_root: Path):
    """Return a tool_handler closure bound to repos_root.

    Signature matches ArchitectAgent pattern:
        handler(tool_name: str, arguments: Dict[str, Any]) -> str
    """
    def handler(tool_name: str, arguments: Dict[str, Any]) -> str:
        try:
            if tool_name == "clone_repo":
                path = clone_repo(
                    git_url   = arguments["git_url"],
                    dest_name = arguments["dest_name"],
                    repos_root= repos_root,
                    auth_token= arguments.get("auth_token"),
                    branch    = arguments.get("branch"),
                    depth     = arguments.get("depth"),
                )
                return json.dumps({"status": "cloned", "path": path})

            elif tool_name == "read_repo_file":
                content = read_repo_file(
                    repo_name  = arguments["repo_name"],
                    file_path  = arguments["file_path"],
                    repos_root = repos_root,
                )
                return content

            elif tool_name == "glob_repo":
                return glob_repo(
                    repo_name   = arguments["repo_name"],
                    pattern     = arguments["pattern"],
                    repos_root  = repos_root,
                    max_results = int(arguments.get("max_results", _MAX_GLOB_RESULTS)),
                )

            elif tool_name == "grep_repo":
                return grep_repo(
                    repo_name     = arguments["repo_name"],
                    pattern       = arguments["pattern"],
                    repos_root    = repos_root,
                    file_glob     = arguments.get("file_glob", "**/*"),
                    max_matches   = int(arguments.get("max_matches", _MAX_GREP_MATCHES)),
                    context_lines = int(arguments.get("context_lines", _DEFAULT_CONTEXT)),
                )

            elif tool_name == "analyze_ast":
                return analyze_ast(
                    repo_name  = arguments["repo_name"],
                    file_path  = arguments["file_path"],
                    repos_root = repos_root,
                )

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name!r}"})

        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return handler
