import json
from datetime import date

from promopilot.datagen import GeneratedDataset, generate, load_config
from promopilot.domain import Segment


def test_default_world_has_four_regions_of_five_stores() -> None:
    stores = generate(load_config(), seed=42).stores

    assert stores.groupby("region").size().to_dict() == {
        "East": 5,
        "North": 5,
        "South": 5,
        "West": 5,
    }
    assert stores["store_id"].is_unique
    assert "Chennai" in set(stores.loc[stores["region"] == "South", "city"])


def test_every_store_has_a_segment_mix_over_the_four_segments(
    small_dataset: GeneratedDataset,
) -> None:
    mixes = [json.loads(mix) for mix in small_dataset.stores["segment_mix"]]

    for mix in mixes:
        assert set(mix) == {segment.value for segment in Segment}
        assert abs(sum(mix.values()) - 1) < 1e-9
        assert min(mix.values()) > 0
    assert len({json.dumps(mix, sort_keys=True) for mix in mixes}) == len(mixes)


def test_calendar_covers_history_and_horizon_for_every_region(
    small_dataset: GeneratedDataset,
) -> None:
    config = small_dataset.config
    calendar = small_dataset.calendar

    assert len(calendar) == config.total_weeks * len(config.regions)
    week_zero = calendar[calendar["week_id"] == 0]["week_start"].unique()
    assert list(week_zero) == [date(2024, 9, 30)]


def diwali_and_pongal_weeks() -> dict[tuple[str, str], float]:
    calendar = generate(load_config(), seed=42).calendar
    # Diwali 2026 falls on Sunday 8 Nov: the week starting Monday 2 Nov is week 109.
    week_109 = calendar[calendar["week_id"] == 109]
    # Pongal 2026 is on 14 Jan: the week starting Monday 12 Jan is week 67.
    week_67 = calendar[calendar["week_id"] == 67]
    intensity: dict[tuple[str, str], float] = {}
    for festival, week in (("Diwali", week_109), ("Pongal", week_67)):
        for region, level in zip(week["region"], week["holiday_intensity"], strict=True):
            intensity[(str(region), festival)] = float(level)
    return intensity


def test_national_festivals_lift_every_region_and_regional_ones_only_their_region() -> None:
    intensity = diwali_and_pongal_weeks()

    assert all(
        intensity[(region, "Diwali")] == 1.0 for region in ["North", "South", "East", "West"]
    )
    assert intensity[("South", "Pongal")] > 0
    assert intensity[("East", "Pongal")] == 0  # North has Lohri that week


def test_the_week_before_a_festival_carries_a_smaller_lead_in_lift() -> None:
    calendar = generate(load_config(), seed=42).calendar
    north = calendar[calendar["region"] == "North"].set_index("week_id")

    assert north.loc[109, "holiday_name"] == "Diwali"
    lead_in, festival = north["holiday_intensity"].loc[[108, 109]].astype(float)
    assert 0 < lead_in < festival
