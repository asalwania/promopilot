"""Brief-to-catalogue resolution: the deterministic reading of the entities a brief names."""

import pytest

from promopilot.agents.resolution import AMBIGUOUS_BELOW, BriefResolver
from promopilot.datagen import GeneratedDataset
from promopilot.domain import PromoWindow, Region
from tests.unit.agents.fakes import InMemoryRetailData

AS_OF = 104
NORTH_AND_WEST = [Region.NORTH, Region.WEST]


async def resolver_at(dataset: GeneratedDataset, as_of_week: int = AS_OF) -> BriefResolver:
    return await BriefResolver.load(InMemoryRetailData(dataset), as_of_week=as_of_week)


@pytest.fixture
async def resolver(default_dataset: GeneratedDataset) -> BriefResolver:
    return await resolver_at(default_dataset)


# The SPEC §3.2 demo brief: "Plan Diwali promotions for Snacks and Beverages across North and
# West. ... We are overstocked on 400g namkeen packs ..."


def test_the_demo_briefs_categories_resolve_exactly(resolver: BriefResolver) -> None:
    resolution = resolver.categories("Snacks and Beverages")

    assert resolution.best is not None
    assert resolution.best.value == ("Snacks", "Beverages")
    assert resolution.best.score == 1.0
    assert not resolution.ambiguous


def test_the_demo_briefs_regions_resolve_exactly(resolver: BriefResolver) -> None:
    resolution = resolver.regions("North and West")

    assert resolution.best is not None
    assert resolution.best.value == (Region.NORTH, Region.WEST)
    assert resolution.best.score == 1.0
    assert not resolution.ambiguous


def test_the_demo_briefs_packs_resolve_to_exactly_the_400g_namkeen_skus(
    resolver: BriefResolver, default_dataset: GeneratedDataset
) -> None:
    resolution = resolver.products("400g namkeen packs")

    products = default_dataset.products
    namkeen_400g = products[
        (products["subcategory"] == "Namkeen") & (products["pack_size"] == "400g")
    ]
    assert resolution.best is not None
    assert resolution.best.value == tuple(namkeen_400g["sku_id"]) == ("SKU0002", "SKU0006")
    assert resolution.best.score == 1.0
    assert not resolution.ambiguous


def test_diwali_resolves_to_the_weeks_the_calendar_labels_diwali(
    resolver: BriefResolver,
) -> None:
    resolution = resolver.promo_window("Diwali", regions=NORTH_AND_WEST)

    assert resolution.best is not None
    assert resolution.best.value == PromoWindow(start_week=108, end_week=109)
    assert resolution.best.score == 1.0
    assert not resolution.ambiguous


# Ambiguity and partial matches


def test_an_ambiguous_phrase_returns_several_candidates_each_below_an_exact_match(
    resolver: BriefResolver,
) -> None:
    resolution = resolver.categories("care products")

    assert resolution.ambiguous
    assert {candidate.value for candidate in resolution.candidates} >= {
        ("Personal Care",),
        ("Home Care",),
    }
    assert all(candidate.score < 1.0 for candidate in resolution.candidates)


def test_a_product_phrase_with_two_readings_scores_the_looser_one_lower(
    resolver: BriefResolver,
) -> None:
    resolution = resolver.products("snacks 400g")

    assert len(resolution.candidates) >= 2
    exact = resolver.products("frozen snacks 400g").best
    assert exact is not None
    assert exact.score == 1.0
    assert resolution.best is not None
    assert resolution.best.score == 1.0
    # "snacks" names the category exactly; reading it as the Frozen Snacks subcategory scores less.
    [frozen] = [c for c in resolution.candidates if c.value == exact.value]
    assert frozen.score < 1.0


def test_a_misspelling_still_resolves_with_a_lower_score(resolver: BriefResolver) -> None:
    resolution = resolver.products("namkin 400g")

    assert resolution.best is not None
    assert resolution.best.value == ("SKU0002", "SKU0006")
    assert AMBIGUOUS_BELOW <= resolution.best.score < 1.0
    assert not resolution.ambiguous


def test_a_region_adjective_resolves_with_a_lower_score(resolver: BriefResolver) -> None:
    resolution = resolver.regions("northern")

    assert resolution.best is not None
    assert resolution.best.value == (Region.NORTH,)
    assert AMBIGUOUS_BELOW <= resolution.best.score < 1.0


@pytest.mark.parametrize("phrase", ["", "the usual", "electronics"])
def test_a_phrase_matching_nothing_has_no_candidates_and_is_ambiguous(
    resolver: BriefResolver, phrase: str
) -> None:
    resolution = resolver.categories(phrase)

    assert resolution.candidates == ()
    assert resolution.best is None
    assert resolution.ambiguous


def test_products_can_be_limited_to_categories(resolver: BriefResolver) -> None:
    resolution = resolver.products("400g", categories=["Dairy"])

    assert resolution.best is not None
    assert resolution.best.value == ("SKU0057", "SKU0059", "SKU0061")


# The as-of week


async def test_the_promo_window_only_uses_weeks_after_the_as_of_week(
    default_dataset: GeneratedDataset,
) -> None:
    during_lead_in = await resolver_at(default_dataset, as_of_week=108)
    after_diwali = await resolver_at(default_dataset, as_of_week=109)

    lead_in = during_lead_in.promo_window("Diwali", regions=NORTH_AND_WEST)
    assert lead_in.best is not None
    assert lead_in.best.value == PromoWindow(start_week=109, end_week=109)
    # Diwali 2027 lies past the generated horizon.
    assert after_diwali.promo_window("Diwali", regions=NORTH_AND_WEST).candidates == ()


def test_a_regional_festival_only_resolves_in_its_regions(resolver: BriefResolver) -> None:
    east = resolver.promo_window("Durga Puja", regions=[Region.EAST])
    west = resolver.promo_window("Durga Puja", regions=[Region.WEST])

    assert east.best is not None
    assert east.best.value == PromoWindow(start_week=106, end_week=107)
    assert west.candidates == ()


async def test_resolution_is_deterministic(default_dataset: GeneratedDataset) -> None:
    first, second = await resolver_at(default_dataset), await resolver_at(default_dataset)

    for phrase in ["care products", "snacks 400g", "namkin", "North and West"]:
        assert first.products(phrase) == second.products(phrase) == first.products(phrase)
        assert first.categories(phrase) == second.categories(phrase)
        assert first.regions(phrase) == second.regions(phrase)


# Every region or category (#46 follow-up, ADR 0053)

ALL_REGIONS = (Region.NORTH, Region.SOUTH, Region.EAST, Region.WEST)


@pytest.mark.parametrize(
    "phrase",
    [
        "all regions",
        "pan-India",
        "Pan India",
        "all-India",
        "nationwide",
        "across India",
        "every region",
        "all four regions",
        "all zones",
    ],
)
def test_a_phrase_naming_every_region_resolves_to_all_of_them(
    resolver: BriefResolver, phrase: str
) -> None:
    resolution = resolver.regions(phrase)

    assert resolution.best is not None
    assert resolution.best.value == ALL_REGIONS
    assert resolution.best.score == 1.0
    assert not resolution.ambiguous


@pytest.mark.parametrize("phrase", ["all categories", "every category", "the entire range"])
def test_a_phrase_naming_every_category_resolves_to_all_of_them(
    resolver: BriefResolver, default_dataset: GeneratedDataset, phrase: str
) -> None:
    resolution = resolver.categories(phrase)

    assert resolution.best is not None
    categories = default_dataset.products.sort_values("sku_id")["category"]
    assert resolution.best.value == tuple(dict.fromkeys(categories))
    assert resolution.best.score == 1.0


def test_every_region_but_one_is_not_read_as_every_region(resolver: BriefResolver) -> None:
    resolution = resolver.regions("all regions except West")

    assert resolution.best is None or resolution.best.value != ALL_REGIONS


# Mentions: the entities a whole text names, for the fallback reading (ADR 0053)

SPEC_BRIEF = (
    "Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. "
    "Keep margin above 18%. We are overstocked on 400g namkeen packs — clear at least 60% of "
    "that stock. Target families."
)


def test_the_spec_briefs_mentions_are_its_regions_categories_holiday_and_packs(
    resolver: BriefResolver,
) -> None:
    mentions = resolver.mentions(SPEC_BRIEF)

    assert mentions.regions == (Region.NORTH, Region.WEST)
    assert mentions.categories == ("Snacks", "Beverages")
    assert mentions.holidays == ("Diwali",)
    assert set(mentions.products) >= {"400g", "Namkeen", "Snacks", "Beverages"}


def test_a_mention_needs_every_word_of_a_term_in_order(resolver: BriefResolver) -> None:
    # Fuzzy neighbours ("month" and North, "best" and West) and scattered words are no mention.
    mentions = resolver.mentions("Our best month for new products this year, with care")

    assert mentions.regions == ()
    assert mentions.categories == ()
    assert mentions.holidays == ()


def test_a_text_naming_every_region_mentions_all_of_them(resolver: BriefResolver) -> None:
    assert resolver.mentions("A pan-India snacks push").regions == ALL_REGIONS
