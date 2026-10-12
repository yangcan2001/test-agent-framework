import pytest

from test_agent.gates import GateConfig, GateExceeded, StepBudget, TaskGate


def test_task_gate_step_limit():
    gate = TaskGate(GateConfig(task_max_steps=2))
    gate.consume_step()
    gate.consume_step()
    with pytest.raises(GateExceeded):
        gate.consume_step()


def test_task_gate_token_limit():
    gate = TaskGate(GateConfig(task_max_tokens=10))
    gate.consume_tokens(7)
    with pytest.raises(GateExceeded):
        gate.consume_tokens(4)


def test_step_budget():
    b = StepBudget(2, 1)
    b.retry_left -= 1
    b.fix_left -= 1
    assert (b.retry_left, b.fix_left) == (1, 0)


def test_step_budget_from_config():
    b = StepBudget.from_config(GateConfig(step_retry_budget=3, step_fix_budget=2))
    assert (b.retry_left, b.fix_left) == (3, 2)
