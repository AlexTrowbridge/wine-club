from decimal import Decimal

from django import forms
from django.db.models import Max

from .models import SCORE_MAX, SCORE_MIN, Era, Member, Session, Tasting
from .services import get_or_create_wine, get_region


class SessionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = ["number", "date", "theme", "era"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            last = Session.objects.aggregate(n=Max("number"))["n"] or 0
            self.initial.setdefault("number", last + 1)
            latest_era = Era.objects.order_by("-start_date").first()
            if latest_era:
                self.initial.setdefault("era", latest_era.pk)


class TastingForm(forms.ModelForm):
    """Add a bottle to a session; the wine is found or created from its full name."""

    wine_name = forms.CharField(
        label="Wine",
        max_length=300,
        help_text="As on the label: Producer Vintage Label Varietals, "
        "e.g. “Henschke 2020 Henry's Seven Shiraz Grenache Mataro Viognier”. "
        "Use NV for non-vintage.",
        widget=forms.TextInput(attrs={"list": "wine-names", "autocomplete": "off"}),
    )
    region = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=100, required=False)
    shared_purchase = forms.BooleanField(
        label="Bought by everyone", required=False, help_text="Club-funded bottle."
    )

    class Meta:
        model = Tasting
        fields = ["position", "purchaser", "shared_purchase", "price", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        self.fields["purchaser"].queryset = Member.objects.filter(active=True)
        if session and not self.instance.pk:
            last = session.tastings.aggregate(n=Max("position"))["n"] or 0
            self.initial.setdefault("position", last + 1)
        if self.instance.pk:
            wine = self.instance.wine
            self.initial["wine_name"] = wine.full_name
            if wine.region:
                self.initial["region"] = wine.region.name
                self.initial["country"] = wine.region.country.name
        self.order_fields(["wine_name", "region", "country"])

    def clean(self):
        data = super().clean()
        if bool(data.get("region")) != bool(data.get("country")):
            raise forms.ValidationError("Give both a region and a country, or neither.")
        if data.get("shared_purchase") and data.get("purchaser"):
            raise forms.ValidationError("Choose a purchaser or ‘bought by everyone’, not both.")
        position = data.get("position")
        if position and self.session:
            clash = self.session.tastings.filter(position=position).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("position", "Another bottle already has this position.")
        return data

    def save(self, commit=True):
        region = get_region(self.cleaned_data["region"], self.cleaned_data["country"])
        self.instance.wine, self.created_wine = get_or_create_wine(
            self.cleaned_data["wine_name"], region
        )
        self.instance.session = self.session
        return super().save(commit)


class ScoreForm(forms.Form):
    """A single score submission.

    ``score`` is a number (steps of 0.5), ``x`` for "tasted but no score", or empty
    to remove the member's rating for that bottle.
    """

    NO_SCORE = "x"

    member = forms.ModelChoiceField(queryset=Member.objects.all(), required=False)
    score = forms.CharField(required=False, max_length=5)

    def clean(self):
        data = super().clean()
        raw = (data.get("score") or "").strip().lower()
        data["clear"] = raw == ""
        if raw in ("", self.NO_SCORE, "-"):
            data["score"] = None
            return data
        try:
            value = Decimal(raw)
        except ArithmeticError:
            raise forms.ValidationError("Enter a score, x (no score) or leave blank.") from None
        if not SCORE_MIN <= value <= SCORE_MAX:
            raise forms.ValidationError(f"Scores run from {SCORE_MIN} to {SCORE_MAX}.")
        if (value * 2) % 1:
            raise forms.ValidationError("Scores are in steps of 0.5.")
        data["score"] = value
        return data


SCORE_CHOICES = [Decimal(n) for n in range(1, 11)]
