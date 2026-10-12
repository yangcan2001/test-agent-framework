from test_agent.gates import StepBudget
from test_agent.llm import FakeLLM
from test_agent.react import DecisionRemapper
from test_agent.reflection import Reflector
from test_agent.types import Action, ExecOutcome, ExecResult


class _Boom:
    def complete(self, messages, *, temperature=0.0):
        raise RuntimeError("llm down")


def test_model_decision_used_when_available():
    reflector = Reflector(FakeLLM({"结果": "fix"}))
    assert reflector.decide("x", ExecResult(ExecOutcome.FAILED, "assert mismatch")) == Action.FIX


def test_keyword_rule_fallback():
    reflector = Reflector(_Boom())
    assert reflector.decide("x", ExecResult(ExecOutcome.FAILED, "AssertionError: expect 200")) == Action.FIX
    assert reflector.decide("x", ExecResult(ExecOutcome.TIMEOUT, "read timeout")) == Action.RETRY


def test_default_decision_when_no_rule_matches():
    reflector = Reflector(_Boom())
    assert reflector.decide("x", ExecResult(ExecOutcome.FAILED, "some mystery")) == Action.CONTINUE


def test_decision_remapping():
    assert DecisionRemapper.remap(Action.RETRY, StepBudget(0, 1)) == Action.FIX
    assert DecisionRemapper.remap(Action.FIX, StepBudget(2, 0)) == Action.CONTINUE
    assert DecisionRemapper.remap(Action.RETRY, StepBudget(0, 0)) == Action.CONTINUE
    assert DecisionRemapper.remap(Action.RETRY, StepBudget(1, 1)) == Action.RETRY
