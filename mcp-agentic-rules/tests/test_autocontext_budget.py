"""
Tests for autocontext budget enforcement.
=========================================
Guards the hard output cap (mixed char/word partition estimates must never
flood an agent's context) and the --budget flag parsing.
"""

import pytest

from scripts.autocontext import _enforce_hard_cap, _parse_budget


class TestHardCap:
    def test_under_budget_untouched(self):
        text = "short payload"
        if _enforce_hard_cap(text, 8000) != text:
            raise AssertionError("payload under budget must pass through unchanged")

    def test_over_budget_truncated_with_notice(self):
        text = "x" * 100000
        capped = _enforce_hard_cap(text, 1000)
        if len(capped) > 4000:
            raise AssertionError("capped output exceeds budget: %d chars" % len(capped))
        if "[TRUNCATED]" not in capped:
            raise AssertionError("truncated output must carry a notice")

    def test_minimum_floor(self):
        capped = _enforce_hard_cap("y" * 100000, 1)
        if len(capped) < 1000:
            raise AssertionError("cap floor must keep output useful")


class TestBudgetFlag:
    def test_parses_and_strips_flag(self):
        budget, rest = _parse_budget(["--budget", "20000", "implement", "filters"])
        if budget != 20000:
            raise AssertionError("budget not parsed, got %r" % budget)
        if rest != ["implement", "filters"]:
            raise AssertionError("flag and value must be stripped, got %r" % rest)

    def test_default_without_flag(self):
        budget, rest = _parse_budget(["some", "task"])
        if budget != 8000 or rest != ["some", "task"]:
            raise AssertionError("default budget handling broken")

    def test_bad_value_falls_back(self):
        budget, rest = _parse_budget(["--budget", "lots", "task"])
        if budget != 8000:
            raise AssertionError("non-numeric budget must fall back to default")
        if "task" not in rest:
            raise AssertionError("positional args must survive")

    def test_floor_applied(self):
        budget, _ = _parse_budget(["--budget", "10"])
        if budget < 500:
            raise AssertionError("budget floor must apply")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
