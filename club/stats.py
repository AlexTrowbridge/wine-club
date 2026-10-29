"""Club statistics, mirroring the analyses in the original workbook's Stats sheet.

The data set is small (hundreds of bottles), so everything is computed in Python
from a single flattened list of scored tastings rather than with elaborate SQL.
Wine-level figures (breakdowns, top wines, price fit) use each bottle's average
score, as the spreadsheet did.
"""

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.db.models import Count, Prefetch, Q

from .models import Era, Member, Rating, Session, Tasting, WineVarietal

# Upper bound (inclusive) and label, as in the workbook's "Price Range" table.
PRICE_BANDS = [
    (15, "$10–15"),
    (20, "$16–20"),
    (25, "$21–25"),
    (30, "$26–30"),
    (35, "$31–35"),
    (45, "$36–45"),
    (60, "$46–60"),
    (99, "$61–99"),
    (math.inf, "$100+"),
]
AGE_CAP = 10  # ages >= this are grouped as "10+"
MIN_FIT_POINTS = 3  # priced bottles needed before fitting rating against price


@dataclass
class Bottle:
    """A scored tasting, flattened for analysis."""

    tasting: Tasting
    avg: float
    n_scores: int
    min: float
    max: float

    @property
    def wine(self):
        return self.tasting.wine

    @property
    def points_100(self):
        """The workbook's 100-point conversion: 50 * avg^0.3."""
        return 50 * self.avg**0.3

    @property
    def spread(self):
        return self.max - self.min


def bottles(tastings=None) -> list[Bottle]:
    qs = (tastings if tastings is not None else Tasting.objects.all()).visible()
    qs = qs.select_related("wine__region__country", "session__era", "purchaser").prefetch_related(
        Prefetch(
            "wine__winevarietal_set",
            queryset=WineVarietal.objects.select_related("varietal"),
        ),
        Prefetch("ratings", queryset=Rating.objects.visible().scored()),
    )
    out = []
    for t in qs:
        scores = [float(r.score) for r in t.ratings.all()]
        if scores:
            out.append(Bottle(t, statistics.fmean(scores), len(scores), min(scores), max(scores)))
    return out


def summarise(values):
    values = list(values)
    if not values:
        return {"n": 0, "mean": None, "median": None, "stdev": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        # Population standard deviation, matching Excel's STDEV.P.
        "stdev": statistics.pstdev(values),
    }


# --- Top wines ------------------------------------------------------------------


def top_wines(data: list[Bottle], n=3, era=None, year=None):
    rows = [
        b
        for b in data
        if (era is None or b.tasting.session.era_id == era.pk)
        and (year is None or b.tasting.session.date.year == year)
    ]
    rows.sort(key=lambda b: (-b.avg, b.tasting.session.date))
    return rows[:n]


def top_wine_groups(data: list[Bottle], n=3):
    """Top wines overall, per era and per calendar year (as in the Stats sheet)."""
    groups = [("Overall", top_wines(data, n))]
    for era in Era.objects.all():
        groups.append((era.name, top_wines(data, n, era=era)))
    for year in sorted({b.tasting.session.date.year for b in data}, reverse=True):
        groups.append((str(year), top_wines(data, n, year=year)))
    return groups


# --- Members --------------------------------------------------------------------


@dataclass
class MemberStats:
    member: Member
    attended: int
    attendance_rate: float
    n_ratings: int
    avg_given: float | None
    bottles_bought: int
    avg_of_purchases: float | None

    @property
    def purchase_difference(self):
        """How the member's wines score relative to how the member scores in general."""
        if self.avg_of_purchases is None or self.avg_given is None:
            return None
        return self.avg_of_purchases - self.avg_given

    @property
    def bottles_per_session(self):
        return self.bottles_bought / self.attended if self.attended else None


def held_session_count() -> int:
    """Sessions that have happened (or are happening); planned ones don't count yet."""
    return Session.objects.exclude(status=Session.Status.PLANNED).count()


def member_stats(data: list[Bottle]) -> list[MemberStats]:
    n_sessions = held_session_count() or 1
    members = Member.objects.annotate(
        n_attended=Count("attendances", distinct=True),
    )
    given = defaultdict(list)
    for member_id, score in Rating.objects.visible().scored().values_list("member_id", "score"):
        given[member_id].append(float(score))
    purchases = defaultdict(list)
    for b in data:
        if b.tasting.purchaser_id:
            purchases[b.tasting.purchaser_id].append(b.avg)
    purchase_counts = dict(
        Tasting.objects.filter(purchaser__isnull=False)
        .values("purchaser_id")
        .annotate(n=Count("id"))
        .values_list("purchaser_id", "n")
    )
    out = []
    for m in members:
        g, p = given.get(m.pk, []), purchases.get(m.pk, [])
        out.append(
            MemberStats(
                member=m,
                attended=m.n_attended,
                attendance_rate=m.n_attended / n_sessions,
                n_ratings=len(g),
                avg_given=statistics.fmean(g) if g else None,
                bottles_bought=purchase_counts.get(m.pk, 0),
                avg_of_purchases=statistics.fmean(p) if p else None,
            )
        )
    return out


def ranked(rows, key, reverse=True):
    """Sort rows by key (skipping None) and attach a competition rank (1, 1, 3...)."""
    rows = [r for r in rows if key(r) is not None]
    rows.sort(key=key, reverse=reverse)
    out, prev, rank = [], object(), 0
    for i, r in enumerate(rows, start=1):
        value = key(r)
        if value != prev:
            rank, prev = i, value
        out.append((rank, r))
    return out


def rating_histogram(member=None):
    qs = Rating.objects.visible().scored()
    if member is not None:
        qs = qs.filter(member=member)
    counts = defaultdict(int)
    for s in qs.values_list("score", flat=True):
        counts[float(s)] += 1
    return dict(sorted(counts.items()))


def purchaser_rater_matrix(data: list[Bottle] | None = None):
    """Average score each rater gives to wines bought by each purchaser.

    Returns (purchasers, raters, cells, diffs) where cells[p][r] is the mean
    score and diffs[p][r] is that minus the rater's overall mean.
    """
    rows = (
        Rating.objects.visible()
        .scored()
        .filter(tasting__purchaser__isnull=False)
        .values_list("tasting__purchaser_id", "member_id", "score")
    )
    acc = defaultdict(list)
    for p, r, s in rows:
        acc[(p, r)].append(float(s))
    overall = defaultdict(list)
    for r, s in Rating.objects.visible().scored().values_list("member_id", "score"):
        overall[r].append(float(s))
    overall_mean = {r: statistics.fmean(v) for r, v in overall.items()}

    members = list(Member.objects.all())
    purchasers = [m for m in members if any(k[0] == m.pk for k in acc)]
    raters = [m for m in members if m.pk in overall_mean]
    cells, diffs = {}, {}
    for p in purchasers:
        for r in raters:
            v = acc.get((p.pk, r.pk))
            if v:
                cells[(p.pk, r.pk)] = (statistics.fmean(v), len(v))
                diffs[(p.pk, r.pk)] = statistics.fmean(v) - overall_mean[r.pk]
    return purchasers, raters, cells, diffs


# --- Breakdowns -----------------------------------------------------------------


def price_band(price):
    if price is None:
        return None
    for upper, label in PRICE_BANDS:
        if price <= upper:
            return label
    return None


def _age_label(b: Bottle):
    age = b.tasting.age_consumed
    if age is None:
        return "NV"
    return f"{AGE_CAP}+" if age >= AGE_CAP else str(age)


def _blend(b: Bottle):
    return "Blend" if b.wine.blend else "Single varietal"


# key -> (title, function bottle -> list of group labels, sort mode)
DIMENSIONS = {
    "varietal": (
        "Varietal (any wine containing it)",
        lambda b: [wv.varietal.name for wv in b.wine.winevarietal_set.all()],
        "mean",
    ),
    "single-varietal": (
        "Varietal (single-varietal wines only)",
        lambda b: (
            [] if b.wine.blend else [wv.varietal.name for wv in b.wine.winevarietal_set.all()][:1]
        ),
        "mean",
    ),
    "blend": ("Single varietal vs blend", lambda b: [_blend(b)], "mean"),
    "vintage": ("Vintage", lambda b: [b.wine.vintage_label], "label"),
    "age": ("Age when consumed (years)", lambda b: [_age_label(b)], "age"),
    "price": (
        "Bottle price",
        lambda b: [price_band(b.tasting.price)] if b.tasting.price is not None else [],
        "price",
    ),
    "region": (
        "Region",
        lambda b: [b.wine.region.name] if b.wine.region else [],
        "mean",
    ),
    "country": (
        "Country",
        lambda b: [b.wine.region.country.name] if b.wine.region else [],
        "mean",
    ),
    "style": (
        "Style",
        lambda b: [b.wine.get_style_display()] if b.wine.style else [],
        "mean",
    ),
    "year": ("Year tasted", lambda b: [str(b.tasting.session.date.year)], "label"),
    "purchaser": (
        "Purchaser",
        lambda b: [b.tasting.purchaser_label] if b.tasting.purchaser_label else [],
        "mean",
    ),
}


def breakdown(data: list[Bottle], dimension: str):
    _, labels_for, sort_mode = DIMENSIONS[dimension]
    groups = defaultdict(list)
    for b in data:
        for label in labels_for(b):
            groups[label].append(b.avg)
    rows = [{"label": label, **summarise(values)} for label, values in groups.items()]
    if sort_mode == "mean":
        rows.sort(key=lambda r: (-r["mean"], -r["n"], r["label"]))
    elif sort_mode == "price":
        order = [label for _, label in PRICE_BANDS]
        rows.sort(key=lambda r: order.index(r["label"]))
    elif sort_mode == "age":
        rows.sort(key=lambda r: -1 if r["label"] == "NV" else int(r["label"].rstrip("+")))
    else:
        rows.sort(key=lambda r: (r["label"] != "NV", r["label"]))
    return rows


# --- Regions --------------------------------------------------------------------


def tastings_per_region() -> dict[int, int]:
    """Visible bottles opened per region pk, scored or not (for the map)."""
    rows = (
        Tasting.objects.visible()
        .filter(wine__region__isnull=False)
        .values("wine__region")
        .annotate(n=Count("id"))
        .order_by()
    )
    return {row["wine__region"]: row["n"] for row in rows}


def region_means(data: list[Bottle]) -> dict[int, float]:
    """Mean bottle score per region pk (keyed by pk: region names repeat across countries)."""
    scores = defaultdict(list)
    for b in data:
        if b.wine.region_id is not None:
            scores[b.wine.region_id].append(b.avg)
    return {region_id: statistics.fmean(values) for region_id, values in scores.items()}


def varietal_counts(data: list[Bottle]) -> list[tuple[str, int]]:
    """How many bottles contained each varietal, most common first."""
    counts = Counter(wv.varietal.name for b in data for wv in b.wine.winevarietal_set.all())
    return counts.most_common()


# --- Price vs rating -------------------------------------------------------------


@dataclass
class PriceFit:
    a: float
    b: float
    r2: float
    n: int

    @property
    def per_doubling(self):
        return self.a * math.log(2)

    def predict(self, price):
        return self.a * math.log(price) + self.b

    def expected_price(self, rating):
        """Price at which the fit predicts ``rating``, or None if no price gets there."""
        if self.a == 0:
            return None
        try:
            return math.exp((rating - self.b) / self.a)
        except OverflowError:
            return None


def priced(data: list[Bottle]) -> list[Bottle]:
    """Bottles with a usable (positive) price, for the log-price analyses."""
    return [b for b in data if b.tasting.price is not None and b.tasting.price > 0]


def price_fit(data: list[Bottle]) -> PriceFit | None:
    """Least-squares fit of rating = a*ln(price) + b over priced bottles."""
    import numpy as np

    pts = [(float(b.tasting.price), b.avg) for b in priced(data)]
    if len(pts) < MIN_FIT_POINTS or len({price for price, _ in pts}) < 2:
        return None
    x = np.log([p for p, _ in pts])
    y = np.array([r for _, r in pts])
    a, b = np.polyfit(x, y, 1)
    residual = y - (a * x + b)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((residual**2).sum()) / ss_tot if ss_tot else 0.0
    return PriceFit(float(a), float(b), r2, len(pts))


# --- Timeline -------------------------------------------------------------------


def session_timeline():
    """(session, mean of bottle averages, number of bottles) in date order."""
    per_session = defaultdict(list)
    for b in bottles():
        per_session[b.tasting.session_id].append(b.avg)
    out = []
    for s in Session.objects.order_by("date"):
        if per_session.get(s.pk):
            out.append((s, statistics.fmean(per_session[s.pk]), len(per_session[s.pk])))
    return out


def attendance_counts():
    return Member.objects.annotate(
        n=Count("attendances", distinct=True),
        bought=Count("purchases", distinct=True),
        rated=Count("ratings", filter=Q(ratings__score__isnull=False), distinct=True),
    )
