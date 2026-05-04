"""Tests for the LLM-as-a-Judge evaluation framework."""

import pytest

from core_orchestrator.judge import LLMJudge, JudgeVerdict


def _mock_llm_high_score(prompt):
    return '{"hallucination": 0.95, "accuracy": 0.9, "relevance": 0.88, "reasoning": "Well implemented"}'


def _mock_llm_low_score(prompt):
    return '{"hallucination": 0.3, "accuracy": 0.4, "relevance": 0.5, "reasoning": "Contains hallucinated APIs"}'


def _mock_llm_broken(prompt):
    raise RuntimeError("Judge LLM unavailable")


def _mock_llm_bad_json(prompt):
    return "I cannot evaluate this in JSON format sorry"


class TestLLMJudge:
    def test_high_score_passes(self):
        judge = LLMJudge(judge_llm=_mock_llm_high_score, threshold=0.7)
        v = judge.evaluate(task="Build a REST API", output="from flask import Flask...")
        assert v.passed
        assert v.overall_score > 0.7
        assert v.hallucination_score == 0.95
        assert v.accuracy_score == 0.9
        assert v.relevance_score == 0.88

    def test_low_score_fails(self):
        judge = LLMJudge(judge_llm=_mock_llm_low_score, threshold=0.7)
        v = judge.evaluate(task="Build X", output="import nonexistent_lib...")
        assert not v.passed
        assert v.overall_score < 0.7
        assert "hallucinated" in v.reasoning

    def test_llm_failure_passes_by_default(self):
        judge = LLMJudge(judge_llm=_mock_llm_broken, threshold=0.7)
        v = judge.evaluate(task="task", output="output")
        assert v.passed
        assert v.overall_score == 1.0
        assert "unavailable" in v.reasoning

    def test_bad_json_passes_by_default(self):
        judge = LLMJudge(judge_llm=_mock_llm_bad_json, threshold=0.7)
        v = judge.evaluate(task="task", output="output")
        assert v.passed

    def test_custom_weights(self):
        judge = LLMJudge(
            judge_llm=_mock_llm_high_score,
            threshold=0.7,
            weights={"hallucination": 0.6, "accuracy": 0.3, "relevance": 0.1},
        )
        v = judge.evaluate(task="task", output="output")
        expected = 0.95 * 0.6 + 0.9 * 0.3 + 0.88 * 0.1
        assert abs(v.overall_score - expected) < 0.01

    def test_custom_threshold(self):
        judge = LLMJudge(judge_llm=_mock_llm_high_score, threshold=0.99)
        v = judge.evaluate(task="task", output="output")
        assert not v.passed

    def test_clamps_out_of_range_scores(self):
        def bad_scores(prompt):
            return '{"hallucination": 1.5, "accuracy": -0.3, "relevance": 0.5, "reasoning": "test"}'

        judge = LLMJudge(judge_llm=bad_scores, threshold=0.5)
        v = judge.evaluate(task="t", output="o")
        assert v.hallucination_score == 1.0
        assert v.accuracy_score == 0.0
        assert v.relevance_score == 0.5
