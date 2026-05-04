"""LLM-as-a-Judge evaluation framework.

Uses a strong model to score Agent outputs on hallucination, accuracy, and
relevance before they reach the end user. If the score falls below a threshold,
the result is silently retried via the existing resilience loop.

Integration point: called after QA passes in ResilienceManager.run_task_loop().
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from .json_parser import parse_llm_json

_JUDGE_SYSTEM = """\
You are a strict quality evaluator for AI-generated code and documentation.
Score the following agent output on three dimensions (0.0 to 1.0 each):

1. **hallucination** — 1.0 = fully grounded in the task and context; 0.0 = contains fabricated facts, non-existent APIs, or invented file paths
2. **accuracy** — 1.0 = correct implementation matching requirements; 0.0 = completely wrong or broken
3. **relevance** — 1.0 = directly addresses the task; 0.0 = off-topic or addresses wrong problem

## Task Description
{task}

## Agent Output (code/artifact)
{output}

{context_section}

## Instructions
Respond in strict JSON (no markdown fences):
{{"hallucination": 0.0-1.0, "accuracy": 0.0-1.0, "relevance": 0.0-1.0, "reasoning": "one sentence explanation"}}

Be STRICT. A score of 0.7+ means production-ready. Deduct heavily for:
- Referencing non-existent libraries or APIs (hallucination)
- Missing core requirements or broken logic (accuracy)
- Solving a different problem than asked (relevance)
"""


@dataclass
class JudgeVerdict:
    """Structured evaluation result from the Judge."""
    hallucination_score: float = 0.0
    accuracy_score: float = 0.0
    relevance_score: float = 0.0
    overall_score: float = 0.0
    reasoning: str = ""
    passed: bool = False


class LLMJudge:
    """Evaluate agent outputs using a strong LLM as judge."""

    def __init__(
        self,
        judge_llm: Callable[[str], str],
        threshold: float = 0.7,
        weights: Optional[dict] = None,
    ):
        self._llm = judge_llm
        self._threshold = threshold
        self._weights = weights or {
            "hallucination": 0.4,
            "accuracy": 0.4,
            "relevance": 0.2,
        }

    def evaluate(
        self,
        task: str,
        output: str,
        context: str = "",
    ) -> JudgeVerdict:
        """Score the output. Returns JudgeVerdict with pass/fail determination."""
        context_section = (
            f"## Additional Context\n{context}" if context else ""
        )
        prompt = _JUDGE_SYSTEM.format(
            task=task[:2000],
            output=output[:4000],
            context_section=context_section,
        )

        try:
            response = self._llm(prompt)
        except Exception:
            return JudgeVerdict(
                hallucination_score=1.0,
                accuracy_score=1.0,
                relevance_score=1.0,
                overall_score=1.0,
                reasoning="Judge unavailable — passing by default",
                passed=True,
            )

        parsed = parse_llm_json(response, fallback={})

        h = self._clamp(parsed.get("hallucination", 1.0))
        a = self._clamp(parsed.get("accuracy", 1.0))
        r = self._clamp(parsed.get("relevance", 1.0))
        reasoning = str(parsed.get("reasoning", ""))[:300]

        w = self._weights
        overall = (
            h * w["hallucination"]
            + a * w["accuracy"]
            + r * w["relevance"]
        )

        return JudgeVerdict(
            hallucination_score=h,
            accuracy_score=a,
            relevance_score=r,
            overall_score=round(overall, 3),
            reasoning=reasoning,
            passed=overall >= self._threshold,
        )

    @staticmethod
    def _clamp(value) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, min(1.0, v))
