import math

import pytest

from club import stats


@pytest.fixture
def data(imported):
    return stats.bottles()


def test_bottle_averages_ignore_unscored(data):
    henschke = next(b for b in data if b.wine.producer == "Henschke")
    assert henschke.avg == pytest.approx(25 / 3)
    assert henschke.n_scores == 3
    assert henschke.points_100 == pytest.approx(50 * (25 / 3) ** 0.3)


def test_top_wines(data):
    top = stats.top_wines(data, n=2)
    assert [b.wine.producer for b in top] == ["Bollinger", "Elysian Springs"]


def test_member_stats(data):
    by_name = {r.member.display_name: r for r in stats.member_stats(data)}
    ava = by_name["Ava"]
    assert ava.avg_given == pytest.approx((9 + 8 + 9 + 6) / 4)
    assert ava.avg_of_purchases == pytest.approx(25 / 3)
    assert ava.bottles_bought == 1
    assert ava.attended == 2
    assert ava.bottles_per_session == 0.5
    assert ava.purchase_difference == pytest.approx(25 / 3 - 8)


def test_breakdown_country_uses_population_stdev(data):
    rows = {r["label"]: r for r in stats.breakdown(data, "country")}
    aus = [25 / 3, 25 / 3, 26 / 4]
    assert rows["Australia"]["n"] == 3
    assert rows["Australia"]["mean"] == pytest.approx(sum(aus) / 3)
    mean = sum(aus) / 3
    assert rows["Australia"]["stdev"] == pytest.approx(
        math.sqrt(sum((x - mean) ** 2 for x in aus) / 3)
    )
    assert rows["France"]["n"] == 1


def test_breakdown_varietal_counts_blends_under_each_grape(data):
    labels = {r["label"] for r in stats.breakdown(data, "varietal")}
    assert {"Shiraz", "Viognier", "Pinot Noir", "Cabernet Sauvignon"} <= labels
    single = {r["label"] for r in stats.breakdown(data, "single-varietal")}
    assert "Viognier" not in single and "Cabernet Sauvignon" in single


def test_price_bands_and_ages(data):
    prices = [r["label"] for r in stats.breakdown(data, "price")]
    assert prices == ["$16–20", "$31–35", "$61–99"]
    ages = [r["label"] for r in stats.breakdown(data, "age")]
    assert ages[0] == "NV"


def test_price_fit_recovers_exact_log_curve(data):
    for b in data:
        b.avg = 0.9 * math.log(float(b.tasting.price)) + 4.0
    fit = stats.price_fit(data)
    assert fit.a == pytest.approx(0.9)
    assert fit.b == pytest.approx(4.0)
    assert fit.r2 == pytest.approx(1.0)
    assert fit.expected_price(fit.predict(50)) == pytest.approx(50)


def test_ranked_ties():
    rows = [3, 5, 5, 1]
    assert [r for r, _ in stats.ranked(rows, key=lambda x: x)] == [1, 1, 3, 4]


def test_purchaser_rater_matrix(imported):
    purchasers, raters, cells, diffs = stats.purchaser_rater_matrix()
    names = {p.display_name for p in purchasers}
    assert names == {"Ava", "Ben", "Cleo"}  # 'Everyone' bottles have no purchaser
    ben = next(p for p in purchasers if p.display_name == "Ben")
    cleo = next(r for r in raters if r.display_name == "Cleo")
    assert cells[(ben.pk, cleo.pk)] == (9.0, 1)
