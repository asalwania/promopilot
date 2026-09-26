"""Evaluation: the oracle (and, in E9, scenarios, metrics and the runner).

The only package besides promopilot.datagen allowed to read the ground truth.
"""

from promopilot.evals.oracle import LineOutcome, Oracle, PlanOutcome

__all__ = ["LineOutcome", "Oracle", "PlanOutcome"]
