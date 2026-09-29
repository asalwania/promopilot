"""Which attempts keep their plan-time objective within the Critic's tolerance of the best one
(ADR 0078): the numbers behind `critic.best_attempt`, outside the agents package (ADR 0049)."""

from promopilot.guardrails import within_objective_tolerance


def test_an_objective_within_the_share_of_the_best_one_is_kept() -> None:
    # 5% of ₹10,000 is ₹500: ₹9,500 is within, ₹9,499.99 is not.
    kept = within_objective_tolerance([10_000.0, 9_500.0, 9_499.99, 12.0], 0.05)

    assert kept == (True, True, False, False)


def test_the_share_is_of_the_best_objectives_size_when_it_is_negative() -> None:
    # The best is -₹1,000; 5% of its size is ₹50, so -₹1,050 is within.
    assert within_objective_tolerance([-1_000.0, -1_050.0, -1_050.01], 0.05) == (
        True,
        True,
        False,
    )


def test_no_objective_is_never_ruled_out_and_rules_nothing_out() -> None:
    assert within_objective_tolerance([None, 100.0, 50.0], 0.05) == (True, True, False)
    assert within_objective_tolerance([None, None], 0.05) == (True, True)


def test_a_zero_tolerance_keeps_only_the_best_objective() -> None:
    assert within_objective_tolerance([100.0, 99.99, 100.0], 0.0) == (True, False, True)
