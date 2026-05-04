"""Fusion Architect Agent — cross-repository architecture analysis and synthesis.

Orchestrates a multi-phase analysis pipeline:

  Phase 1 — Clone:    Clone all specified repositories via the universal Git fetcher.
  Phase 2 — Explore:  Recursively read, grep, and AST-analyse each codebase to
                      understand its structure, patterns, and design decisions.
  Phase 3 — Synthesise: Produce a "fusion architecture" report that combines the
                       best elements of all analysed repositories.
  Phase 4 — Persist:  Automatically promote the fusion report to a reusable
                       Markdown skill file via ReflectionAgent._maybe_promote_to_skill(),
                       so future CEO/Architect agents can discover it via SkillLoader.

Usage:
    agent = FusionArchitectAgent(
        tool_llm    = router.as_tool_llm(),
        repos_root  = Path("workspaces/fusion_ws/repos"),
        analysis_goal = "Compare authentication strategies across three auth libraries",
    )
    report = agent.run(repos=[
        {"git_url": "https://github.com/org/repo-a", "dest_name": "repo-a"},
        {"git_url": "https://github.com/org/repo-b", "dest_name": "repo-b",
         "auth_token": "ghp_xxx"},
    ])

Design notes:
- FusionArchitectAgent is stateless: each run() call is independent.
- Knowledge persistence is best-effort: failures never crash the agent.
- The agent receives WRITE_FUSION_REPORT_TOOL as its "submit" action;
  the tool handler intercepts it, stores the report, and sets a flag so
  the LLM loop terminates cleanly.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .git_fetcher import (
    CLONE_REPO_TOOL,
    READ_REPO_FILE_TOOL,
    GLOB_REPO_TOOL,
    GREP_REPO_TOOL,
    ANALYZE_AST_TOOL,
    WRITE_FUSION_REPORT_TOOL,
    make_tool_handler,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FusionReport:
    """Structured output of a completed fusion analysis."""
    title:                str
    repos_analyzed:       List[str]
    strengths_per_repo:   str
    design_tradeoffs:     str
    fusion_architecture:  str
    implementation_steps: str
    tags:                 List[str] = field(default_factory=list)
    skill_id:             Optional[str] = None   # set after knowledge persistence
    skill_path:           Optional[str] = None   # path to saved .md file


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_FUSION_SYSTEM = """\
You are a world-class software architect specialising in cross-repository \
analysis and architectural synthesis.

## Your Mission

{analysis_goal}

## Available Repositories

{repo_list}

## Workflow (follow this ORDER strictly)

### Step 1 — Clone all repositories
Call clone_repo once for each repository listed above.

### Step 2 — Explore each repository
For EACH repository:
a. Call glob_repo with pattern "**/*.py" (or the primary language) to see the file tree.
b. Read key files: README, main entry point, core modules.
c. Call analyze_ast on 2-4 representative source files per repo.
d. Call grep_repo to search for key patterns (e.g. authentication, routing, data models).

### Step 3 — Deep comparison
After exploring all repos, compare:
- Entry point architecture and bootstrapping patterns
- Dependency management and external integrations
- Error handling and resilience strategies
- Testing approach and test coverage signals
- Configuration and environment management
- Key algorithmic or design innovations in each repo

### Step 4 — Write the fusion report
When you have enough information (after reading at least 3 files per repo),
call write_fusion_report EXACTLY ONCE with:
- title: concise name for the fusion architecture
- repos_analyzed: list of repo dest_names you explored
- strengths_per_repo: what each repo does particularly well
- design_tradeoffs: the key trade-offs you observed across repos
- fusion_architecture: your recommended architecture combining the best elements,
  with code examples where helpful
- implementation_steps: ordered list of steps to build the fusion architecture
- tags: technology / domain tags for knowledge indexing

## Rules
- You MUST call clone_repo before reading any repo files.
- You MUST call write_fusion_report to submit your report (never output it as text).
- Be SPECIFIC: name actual files, classes, functions you found.
- Include code snippets in fusion_architecture where they add clarity.
- IRON RULE: All output MUST be in English.
"""

_NO_REPOS = "(no repositories specified)"


# ---------------------------------------------------------------------------
# FusionArchitectAgent
# ---------------------------------------------------------------------------

class FusionArchitectAgent:
    """Analyses multiple Git repositories and synthesises a fusion architecture.

    Parameters
    ----------
    tool_llm:
        Tool-use callable from ModelRouter.as_tool_llm().
        Signature: (system, user_prompt, tools, tool_handler=None) -> List[ToolCall]
    repos_root:
        Absolute path to the directory where repos will be cloned.
        Created automatically if it does not exist.
    analysis_goal:
        Natural-language description of what the analysis should focus on.
    bus:
        Optional event bus for emitting progress events.
    """

    _ALL_TOOLS = [
        CLONE_REPO_TOOL,
        READ_REPO_FILE_TOOL,
        GLOB_REPO_TOOL,
        GREP_REPO_TOOL,
        ANALYZE_AST_TOOL,
        WRITE_FUSION_REPORT_TOOL,
    ]

    def __init__(
        self,
        tool_llm: Callable,
        repos_root: Path,
        analysis_goal: str = "Analyse and synthesise the architecture of the provided repositories.",
        bus: Any = None,
    ) -> None:
        self._tool_llm     = tool_llm
        self._repos_root   = repos_root
        self._analysis_goal = analysis_goal
        self._bus          = bus

        # Ensure repos directory exists
        self._repos_root.mkdir(parents=True, exist_ok=True)

        # Report storage: set by write_fusion_report handler
        self._report: Optional[FusionReport] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, repos: List[Dict[str, Any]]) -> Optional[FusionReport]:
        """Execute the full analysis pipeline.

        Parameters
        ----------
        repos:
            List of dicts, each with:
            - git_url (required): the remote URL
            - dest_name (required): local directory name
            - auth_token (optional): PAT or SSH key path
            - branch (optional): branch/tag to check out
            - depth (optional): shallow clone depth

        Returns
        -------
        FusionReport or None if analysis could not be completed.
        """
        if self._bus:
            self._bus.emit("fusion.start", repo_count=len(repos))

        # Build the system prompt
        repo_list_text = "\n".join(
            f"- **{r['dest_name']}**: {r['git_url']}"
            for r in repos
        ) or _NO_REPOS

        system_prompt = _FUSION_SYSTEM.format(
            analysis_goal=self._analysis_goal,
            repo_list=repo_list_text,
        )

        user_prompt = (
            f"Please analyse the following {len(repos)} repositor"
            f"{'y' if len(repos) == 1 else 'ies'} and produce a fusion "
            f"architecture report.\n\nAnalysis goal: {self._analysis_goal}"
        )

        # Build tool handler: base git handler + write_fusion_report intercept
        base_handler  = make_tool_handler(self._repos_root)
        tool_handler  = self._make_tool_handler(base_handler, repos)

        # Run the tool-use loop
        try:
            self._tool_llm(
                system_prompt,
                user_prompt,
                self._ALL_TOOLS,
                tool_handler,
            )
        except Exception as exc:
            logger.warning("FusionArchitectAgent tool_llm error: %s", exc)

        if self._report is None:
            if self._bus:
                self._bus.emit("fusion.no_report")
            return None

        # Persist to skill system
        self._persist_as_skill(self._report)

        if self._bus:
            self._bus.emit(
                "fusion.complete",
                title=self._report.title,
                skill_id=self._report.skill_id,
            )

        return self._report

    # ------------------------------------------------------------------
    # Tool handler
    # ------------------------------------------------------------------

    def _make_tool_handler(
        self,
        base_handler: Callable,
        repos: List[Dict[str, Any]],
    ) -> Callable:
        """Wrap the base git tool handler to intercept write_fusion_report."""

        # Build an auth_token lookup so the LLM doesn't need to re-specify tokens
        # for repos it already knows were specified upfront.
        token_map: Dict[str, Optional[str]] = {
            r["dest_name"]: r.get("auth_token")
            for r in repos
        }

        def handler(tool_name: str, arguments: Dict[str, Any]) -> str:
            # Intercept the fusion report submission tool
            if tool_name == "write_fusion_report":
                return self._handle_write_fusion_report(arguments)

            # Auto-inject auth_token for clone_repo if not provided by LLM
            if tool_name == "clone_repo":
                dest = arguments.get("dest_name", "")
                if "auth_token" not in arguments and dest in token_map:
                    token = token_map[dest]
                    if token:
                        arguments = {**arguments, "auth_token": token}

            if self._bus:
                self._bus.emit("fusion.tool_call", tool=tool_name)

            return base_handler(tool_name, arguments)

        return handler

    def _handle_write_fusion_report(self, args: Dict[str, Any]) -> str:
        """Intercept write_fusion_report, store result, signal loop termination."""
        try:
            self._report = FusionReport(
                title                = args.get("title", "Fusion Architecture"),
                repos_analyzed       = args.get("repos_analyzed", []),
                strengths_per_repo   = args.get("strengths_per_repo", ""),
                design_tradeoffs     = args.get("design_tradeoffs", ""),
                fusion_architecture  = args.get("fusion_architecture", ""),
                implementation_steps = args.get("implementation_steps", ""),
                tags                 = args.get("tags", []),
            )
            return json.dumps({"status": "report_received", "title": self._report.title})
        except Exception as exc:
            return json.dumps({"error": f"Failed to store report: {exc}"})

    # ------------------------------------------------------------------
    # Knowledge persistence
    # ------------------------------------------------------------------

    def _persist_as_skill(self, report: FusionReport) -> None:
        """Promote the fusion report to a reusable Markdown skill via ReflectionAgent."""
        try:
            from .reflection_agent import ReflectionAgent

            # Build the full Markdown body for the solution field
            solution_body = self._build_skill_markdown(report)

            # Ensure tags include 'architecture' and 'fusion' for proper categorisation
            tags = list(report.tags)
            for mandatory_tag in ("architecture", "fusion"):
                if mandatory_tag not in tags:
                    tags.append(mandatory_tag)

            lesson: Dict[str, Any] = {
                "type":             "architectural_decision",
                "problem":          f"Cross-repo fusion: {report.title}",
                "solution":         solution_body,
                "symptoms":         "",
                "failed_attempts":  "",
                "root_cause":       "",
                "context":          f"Repos analysed: {', '.join(report.repos_analyzed)}",
                "tags":             tags,
            }

            sol_id = uuid.uuid4().hex[:8]
            ReflectionAgent._maybe_promote_to_skill(sol_id, lesson)
            report.skill_id = ReflectionAgent._slug(report.title)

            # Find where the skill was written
            from .reflection_agent import _SKILLS_DIR
            cat_dir = _SKILLS_DIR / ReflectionAgent._infer_category(tags)
            skill_file = cat_dir / f"{report.skill_id}.md"
            if skill_file.exists():
                report.skill_path = str(skill_file)

        except Exception as exc:
            logger.warning("FusionArchitectAgent: skill persistence failed: %s", exc)

    @staticmethod
    def _build_skill_markdown(report: FusionReport) -> str:
        """Assemble the full Markdown body for the skill file."""
        sections = [
            f"# {report.title}",
            "",
            f"**Repositories analysed:** {', '.join(report.repos_analyzed)}",
            "",
            "## Strengths Per Repository",
            report.strengths_per_repo,
            "",
            "## Design Trade-offs",
            report.design_tradeoffs,
            "",
            "## Fusion Architecture",
            report.fusion_architecture,
            "",
            "## Implementation Steps",
            report.implementation_steps,
        ]
        return "\n".join(sections)
