from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def score(value, places=2):
    """Format a score: whole numbers without decimals, averages to `places`."""
    if value is None or value == "":
        return ""
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


@register.filter
def signed(value, places=2):
    if value is None:
        return ""
    return f"{float(value):+.{places}f}"


@register.filter
def pct(value):
    if value is None:
        return ""
    return f"{100 * float(value):.0f}%"


@register.filter
def money(value):
    if value is None or value == "":
        return ""
    value = float(value)
    return f"${value:,.0f}" if value.is_integer() else f"${value:,.2f}"


@register.simple_tag
def heat(diff, scale=1.5):
    """Background for a purchaser-vs-rater cell: green above the rater's norm, red below."""
    if diff is None:
        return ""
    strength = min(abs(float(diff)) / scale, 1.0)
    colour = "47,125,79" if diff > 0 else "179,38,30"
    return format_html("background: rgba({}, {});", colour, f"{0.08 + 0.55 * strength:.2f}")


@register.simple_tag(takes_context=True)
def query(context, **kwargs):
    """Current query string with some parameters replaced (for sort links)."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + params.urlencode()
