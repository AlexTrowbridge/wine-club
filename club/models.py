from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.urls import reverse

from .scoring_tokens import TOKEN_LENGTH, generate_token

SCORE_MIN = Decimal("0")
SCORE_MAX = Decimal("10")


class Member(models.Model):
    display_name = models.CharField(max_length=100, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member",
        help_text="Login account, if this member signs in. Historic members may have none.",
    )
    active = models.BooleanField(default=True)
    joined = models.DateField(null=True, blank=True)
    # Column order in the original spreadsheet; keeps grids in a familiar order.
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "display_name"]

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("member_detail", args=[self.pk])


class Era(models.Model):
    name = models.CharField(max_length=100, unique=True)
    start_date = models.DateField()

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return self.name


class SessionQuerySet(models.QuerySet):
    def with_counts(self):
        return self.annotate(
            n_wines=Count("tastings", distinct=True),
            n_attendees=Count("attendances", distinct=True),
        )

    def open_with_token(self, token):
        """The session currently open for scoring under ``token``, or None."""
        return self.filter(status=Session.Status.OPEN, scoring_token=token).first()


class Session(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        OPEN = "open", "Open for scoring"
        CLOSED = "closed", "Closed"

    number = models.PositiveIntegerField(unique=True)
    date = models.DateField(unique=True)
    theme = models.CharField(max_length=200, blank=True)
    era = models.ForeignKey(Era, on_delete=models.PROTECT, related_name="sessions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    scores_revealed = models.BooleanField(
        default=False,
        help_text="While a session is open, members only see their own scores until revealed.",
    )
    scoring_token = models.CharField(
        max_length=TOKEN_LENGTH,
        null=True,
        blank=True,
        unique=True,
        editable=False,
        help_text="Code for scoring without a login; set while the session is open.",
    )

    objects = SessionQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"#{self.number} – {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        """Keep the scoring code in step with the status: issued on opening, revoked after."""
        before = self.scoring_token
        if not self.is_open:
            self.scoring_token = None
        elif not self.scoring_token:
            self.scoring_token = unused_scoring_token()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and self.scoring_token != before:
            kwargs["update_fields"] = {*update_fields, "scoring_token"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("session_detail", args=[self.number])

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


def unused_scoring_token():
    while True:
        token = generate_token()
        if not Session.objects.filter(scoring_token=token).exists():
            return token


class Attendance(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="attendances")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="attendances")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "member"], name="unique_attendance")
        ]

    def __str__(self):
        return f"{self.member} @ {self.session}"


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self):
        return self.name


class Region(models.Model):
    name = models.CharField(max_length=100)
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="regions")

    class Meta:
        ordering = ["country__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "country"], name="unique_region_per_country")
        ]

    def __str__(self):
        return f"{self.name}, {self.country}"


class Varietal(models.Model):
    name = models.CharField(max_length=100, unique=True)
    aliases = models.CharField(
        max_length=300,
        blank=True,
        help_text="Comma-separated alternative names as they appear in wine names "
        "(e.g. 'Mataro, Monastrell' for Mourvèdre).",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def alias_list(self):
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class Wine(models.Model):
    class Style(models.TextChoices):
        RED = "red", "Red"
        WHITE = "white", "White"
        ROSE = "rose", "Rosé"
        SPARKLING = "sparkling", "Sparkling"
        FORTIFIED = "fortified", "Fortified"
        ORANGE = "orange", "Orange"
        DESSERT = "dessert", "Dessert"

    producer = models.CharField(max_length=200)
    vintage = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Blank for NV.")
    cuvee = models.CharField("cuvée / label", max_length=200, blank=True)
    # Exactly as written in the spreadsheet, so displays and exports round-trip.
    full_name = models.CharField(max_length=300, unique=True)
    varietals = models.ManyToManyField(Varietal, through="WineVarietal", related_name="wines")
    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.PROTECT, related_name="wines"
    )
    style = models.CharField(max_length=10, choices=Style.choices, blank=True)
    is_blend = models.BooleanField(
        null=True,
        blank=True,
        help_text="Leave blank to infer from the number of varietals.",
    )
    jh_score = models.PositiveSmallIntegerField(
        "James Halliday score",
        null=True,
        blank=True,
        validators=[MinValueValidator(50), MaxValueValidator(100)],
    )

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse("wine_detail", args=[self.pk])

    @property
    def vintage_label(self):
        return str(self.vintage) if self.vintage else "NV"

    @property
    def blend(self):
        if self.is_blend is not None:
            return self.is_blend
        return len(self.winevarietal_set.all()) > 1

    def compose_name(self):
        """Rebuild the spreadsheet-style name from structured fields."""
        parts = [self.producer, self.vintage_label, self.cuvee]
        parts += [wv.varietal.name for wv in self.winevarietal_set.select_related("varietal")]
        return " ".join(p for p in parts if p)


class WineVarietal(models.Model):
    wine = models.ForeignKey(Wine, on_delete=models.CASCADE)
    varietal = models.ForeignKey(Varietal, on_delete=models.PROTECT)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["wine", "varietal"], name="unique_wine_varietal")
        ]

    def __str__(self):
        return f"{self.wine} – {self.varietal}"


# Scores of an open session stay hidden (everywhere, including stats) until revealed.
HIDDEN_SESSION = Q(status="open", scores_revealed=False)


class TastingQuerySet(models.QuerySet):
    def visible(self):
        return self.exclude(session__in=Session.objects.filter(HIDDEN_SESSION))

    def with_scores(self):
        scored = Q(ratings__score__isnull=False)
        return self.annotate(
            avg_score=Avg("ratings__score", filter=scored),
            n_scores=Count("ratings", filter=scored),
        )

    def scored(self):
        return self.with_scores().filter(n_scores__gt=0)


class Tasting(models.Model):
    """One bottle of a wine opened at a session."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="tastings")
    wine = models.ForeignKey(Wine, on_delete=models.PROTECT, related_name="tastings")
    position = models.PositiveSmallIntegerField(help_text="Order poured within the session.")
    purchaser = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchases",
    )
    shared_purchase = models.BooleanField(
        default=False, help_text="Bought by the whole club ('Everyone')."
    )
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    # Spreadsheet row number (#), kept for traceability with the original workbook.
    legacy_number = models.PositiveIntegerField(null=True, blank=True, unique=True)

    objects = TastingQuerySet.as_manager()

    class Meta:
        ordering = ["session__date", "position"]
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_pour_position")
        ]

    def __str__(self):
        return f"{self.wine} ({self.session})"

    @property
    def purchaser_label(self):
        if self.shared_purchase:
            return "Everyone"
        return str(self.purchaser) if self.purchaser else ""

    @property
    def age_consumed(self):
        if self.wine.vintage is None:
            return None
        return self.session.date.year - self.wine.vintage


class RatingQuerySet(models.QuerySet):
    def visible(self):
        return self.exclude(tasting__session__in=Session.objects.filter(HIDDEN_SESSION))

    def scored(self):
        return self.filter(score__isnull=False)


class Rating(models.Model):
    tasting = models.ForeignKey(Tasting, on_delete=models.CASCADE, related_name="ratings")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="ratings")
    score = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(SCORE_MIN), MaxValueValidator(SCORE_MAX)],
        help_text="Blank = tasted but did not score.",
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = RatingQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tasting", "member"], name="unique_rating"),
            models.CheckConstraint(
                condition=Q(score__isnull=True) | Q(score__gte=SCORE_MIN, score__lte=SCORE_MAX),
                name="score_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.member}: {self.score} – {self.tasting.wine}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        Attendance.objects.get_or_create(session_id=self.tasting.session_id, member=self.member)


class WorkbookSource(models.Model):
    """Singleton: where the live club workbook lives, and how the last import went."""

    SINGLETON_PK = 1

    url = models.URLField(
        "workbook link",
        max_length=500,
        blank=True,
        help_text="Box shared link to Wine Club.xlsx, e.g. https://….box.com/s/<token>.",
    )
    last_imported_at = models.DateTimeField(null=True, blank=True)
    last_imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_ok = models.BooleanField("last import succeeded", null=True, blank=True)
    last_summary = models.TextField(blank=True)

    class Meta:
        verbose_name = "workbook import"
        verbose_name_plural = "workbook import"

    def __str__(self):
        return "Workbook import"

    @classmethod
    def load(cls):
        source, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return source
