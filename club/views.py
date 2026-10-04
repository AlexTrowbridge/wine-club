import statistics
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.db.models import Count, Prefetch
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import stats
from .forms import SCORE_CHOICES, ScoreForm, SessionForm, TastingForm
from .models import Attendance, Country, Era, Member, Rating, Session, Tasting, Varietal, Wine
from .permissions import (
    can_rate,
    can_see_scores,
    is_organiser,
    member_for,
    organiser_required,
)

# --- Health -----------------------------------------------------------------------


@login_not_required
def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


@login_not_required
def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - report any DB failure as not ready
        return JsonResponse({"status": "unavailable", "error": str(exc)}, status=503)
    return JsonResponse({"status": "ok"})


# --- Dashboard --------------------------------------------------------------------


def dashboard(request):
    today = timezone.localdate()
    open_sessions = Session.objects.filter(status=Session.Status.OPEN).order_by("date")
    upcoming = (
        Session.objects.filter(status=Session.Status.PLANNED, date__gte=today)
        .order_by("date")
        .first()
    )
    last = Session.objects.filter(status=Session.Status.CLOSED).order_by("-date").first()
    last_results = stats.bottles(last.tastings.all()) if last else []
    last_results.sort(key=lambda b: -b.avg)
    timeline = stats.session_timeline()
    return render(
        request,
        "club/dashboard.html",
        {
            "open_sessions": open_sessions,
            "upcoming": upcoming,
            "last": last,
            "last_results": last_results,
            "totals": {
                "sessions": Session.objects.count(),
                "bottles": Tasting.objects.count(),
                "wines": Wine.objects.count(),
                "members": Member.objects.filter(active=True).count(),
                "ratings": Rating.objects.visible().scored().count(),
            },
            "timeline_chart": _timeline_chart(timeline),
        },
    )


def _timeline_chart(timeline):
    window = 5
    values = [avg for _, avg, _ in timeline]
    rolling = [
        round(statistics.fmean(values[max(0, i - window + 1) : i + 1]), 3)
        for i in range(len(values))
    ]
    return {
        "type": "line",
        "data": {
            "labels": [s.date.isoformat() for s, _, _ in timeline],
            "datasets": [
                {
                    "label": "Session average",
                    "data": [round(v, 3) for v in values],
                    "showLine": False,
                    "pointRadius": 3,
                },
                {"label": f"{window}-session rolling mean", "data": rolling, "pointRadius": 0},
            ],
        },
        "options": {"scales": {"y": {"title": {"display": True, "text": "Average score"}}}},
    }


# --- Sessions ---------------------------------------------------------------------


def session_list(request):
    sessions = Session.objects.with_counts().select_related("era")
    return render(request, "club/session_list.html", {"sessions": sessions})


def _session_grid(session, user):
    """Rows of (tasting, avg, cells) for the session's score grid."""
    show_all = can_see_scores(user, session)
    me = member_for(user)
    tastings = list(
        session.tastings.select_related("wine", "purchaser").prefetch_related(
            Prefetch("ratings", queryset=Rating.objects.select_related("member"))
        )
    )
    attendee_ids = set(session.attendances.values_list("member_id", flat=True))
    for t in tastings:
        attendee_ids.update(r.member_id for r in t.ratings.all())
    columns = list(Member.objects.filter(pk__in=attendee_ids))
    rows = []
    for t in tastings:
        by_member = {r.member_id: r for r in t.ratings.all()}
        scores = [float(r.score) for r in t.ratings.all() if r.score is not None]
        cells = []
        for m in columns:
            rating = by_member.get(m.pk)
            visible = show_all or (me is not None and me.pk == m.pk)
            cells.append({"member": m, "rating": rating, "visible": visible})
        rows.append(
            {
                "tasting": t,
                "avg": statistics.fmean(scores) if scores and show_all else None,
                "n": len(scores),
                "cells": cells,
            }
        )
    return columns, rows


def session_detail(request, number):
    session = get_object_or_404(Session.objects.select_related("era"), number=number)
    columns, rows = _session_grid(session, request.user)
    absent = Member.objects.filter(active=True).exclude(pk__in=[m.pk for m in columns])
    return render(
        request,
        "club/session_detail.html",
        {
            "session": session,
            "columns": columns,
            "rows": rows,
            "show_scores": can_see_scores(request.user, session),
            "absent_members": absent,
            "prev": Session.objects.filter(date__lt=session.date).order_by("-date").first(),
            "next": Session.objects.filter(date__gt=session.date).order_by("date").first(),
        },
    )


@organiser_required
def session_edit(request, number=None):
    session = get_object_or_404(Session, number=number) if number else None
    form = SessionForm(request.POST or None, instance=session)
    if request.method == "POST" and form.is_valid():
        session = form.save()
        messages.success(request, f"Saved session {session}.")
        return redirect(session)
    return render(request, "club/form.html", {"form": form, "title": "Session"})


@organiser_required
@require_POST
def session_status(request, number):
    session = get_object_or_404(Session, number=number)
    action = request.POST.get("action")
    if action == "open":
        session.status = Session.Status.OPEN
        session.scores_revealed = False
    elif action == "close":
        session.status = Session.Status.CLOSED
        session.scores_revealed = True
    elif action == "reveal":
        session.scores_revealed = True
    elif action == "hide":
        session.scores_revealed = False
    elif action == "plan":
        session.status = Session.Status.PLANNED
    else:
        return HttpResponseBadRequest("unknown action")
    session.save(update_fields=["status", "scores_revealed"])
    return redirect(session)


@organiser_required
@require_POST
def session_attendance(request, number):
    session = get_object_or_404(Session, number=number)
    member = get_object_or_404(Member, pk=request.POST.get("member"))
    if request.POST.get("action") == "remove":
        if Rating.objects.filter(tasting__session=session, member=member).exists():
            messages.error(request, f"{member} has scores in this session; remove those first.")
        else:
            Attendance.objects.filter(session=session, member=member).delete()
    else:
        Attendance.objects.get_or_create(session=session, member=member)
    return redirect(session)


@organiser_required
def tasting_edit(request, number, pk=None):
    session = get_object_or_404(Session, number=number)
    tasting = get_object_or_404(Tasting, pk=pk, session=session) if pk else None
    form = TastingForm(request.POST or None, instance=tasting, session=session)
    if request.method == "POST":
        if "delete" in request.POST and tasting:
            if tasting.ratings.exists():
                messages.error(request, "This bottle has scores; it can't be deleted.")
            else:
                tasting.delete()
                return redirect(session)
        elif form.is_valid():
            tasting = form.save()
            if tasting.purchaser:
                Attendance.objects.get_or_create(session=session, member=tasting.purchaser)
            if form.created_wine:
                parsed = tasting.wine
                varietals = ", ".join(str(v) for v in parsed.varietals.all()) or "none recognised"
                messages.info(
                    request,
                    f"New wine added: {parsed.producer} · {parsed.vintage_label} · "
                    f"{parsed.cuvee or '—'} · varietals: {varietals}. "
                    "Fix details in admin if this is wrong.",
                )
            return redirect(session)
    return render(
        request,
        "club/tasting_form.html",
        {
            "form": form,
            "session": session,
            "tasting": tasting,
            "wine_names": Wine.objects.values_list("full_name", flat=True),
        },
    )


def session_score(request, number):
    """Phone-friendly page for scoring tonight's wines."""
    session = get_object_or_404(Session, number=number)
    me = member_for(request.user)
    organiser = is_organiser(request.user)
    member = me
    if organiser and request.GET.get("member"):
        member = get_object_or_404(Member, pk=request.GET["member"])
    tastings = list(session.tastings.select_related("wine", "purchaser"))
    mine = {}
    if member:
        mine = {
            r.tasting_id: r for r in Rating.objects.filter(tasting__session=session, member=member)
        }
    items = [
        {
            "tasting": t,
            "rating": mine.get(t.pk),
            "can_rate": member is not None and can_rate(request.user, t, member),
        }
        for t in tastings
    ]
    return render(
        request,
        "club/session_score.html",
        {
            "session": session,
            "member": member,
            "items": items,
            "choices": SCORE_CHOICES,
            "members": Member.objects.filter(active=True) if organiser else None,
        },
    )


@require_POST
def rate(request, pk):
    tasting = get_object_or_404(Tasting.objects.select_related("session", "wine"), pk=pk)
    form = ScoreForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest(" ".join(form.non_field_errors()) or "Invalid score")
    member = form.cleaned_data["member"] or member_for(request.user)
    if member is None:
        return HttpResponseBadRequest("Your login isn't linked to a club member yet.")
    if not can_rate(request.user, tasting, member):
        return HttpResponse("Scoring is closed for this session.", status=403)

    rating = None
    if form.cleaned_data["clear"]:
        Rating.objects.filter(tasting=tasting, member=member).delete()
    else:
        rating, _ = Rating.objects.update_or_create(
            tasting=tasting,
            member=member,
            defaults={"score": form.cleaned_data["score"], "entered_by": request.user},
        )

    if request.headers.get("HX-Request"):
        if request.POST.get("ui") == "grid":
            cell = {"member": member, "rating": rating, "visible": True}
            return render(
                request, "club/_grid_cell.html", {"cell": cell, "tasting": tasting, "saved": True}
            )
        item = {"tasting": tasting, "rating": rating, "can_rate": True}
        return render(
            request,
            "club/_score_item.html",
            {"item": item, "member": member, "choices": SCORE_CHOICES, "session": tasting.session},
        )
    return redirect(tasting.session)


# --- Wines ------------------------------------------------------------------------

WINE_SORTS = {
    "score": lambda b: -b.avg,
    "date": lambda b: b.tasting.session.date,
    "-date": lambda b: -b.tasting.session.date.toordinal(),
    "name": lambda b: b.wine.full_name.lower(),
    "price": lambda b: (b.tasting.price is None, b.tasting.price or 0),
    "vintage": lambda b: b.wine.vintage or 0,
}


def wine_list(request):
    qs = Tasting.objects.all()
    f = request.GET
    if q := f.get("q", "").strip():
        qs = qs.filter(wine__full_name__icontains=q)
    if f.get("country"):
        qs = qs.filter(wine__region__country_id=f["country"])
    if f.get("varietal"):
        qs = qs.filter(wine__varietals=f["varietal"])
    if f.get("era"):
        qs = qs.filter(session__era_id=f["era"])
    if f.get("year"):
        qs = qs.filter(session__date__year=f["year"])
    if f.get("purchaser"):
        qs = qs.filter(purchaser_id=f["purchaser"])
    if f.get("style"):
        qs = qs.filter(wine__style=f["style"])
    data = stats.bottles(qs)
    if f.get("blend") in ("blend", "single"):
        want = f["blend"] == "blend"
        data = [b for b in data if b.wine.blend == want]
    sort = f.get("sort", "-date")
    data.sort(key=WINE_SORTS.get(sort, WINE_SORTS["-date"]))
    years = sorted({d.year for d in Session.objects.dates("date", "year")}, reverse=True)
    return render(
        request,
        "club/wine_list.html",
        {
            "bottles": data,
            "sort": sort,
            "filters": f,
            "countries": Country.objects.all(),
            "varietals": Varietal.objects.annotate(n=Count("wines")).filter(n__gt=0),
            "eras": Era.objects.all(),
            "years": years,
            "purchasers": Member.objects.annotate(n=Count("purchases")).filter(n__gt=0),
            "styles": Wine.Style.choices,
        },
    )


def wine_detail(request, pk):
    wine = get_object_or_404(
        Wine.objects.select_related("region__country").prefetch_related("varietals"), pk=pk
    )
    tastings = []
    for t in wine.tastings.visible().select_related("session", "purchaser"):
        ratings = list(t.ratings.select_related("member").order_by("member__sort_order"))
        scores = [float(r.score) for r in ratings if r.score is not None]
        tastings.append(
            {
                "tasting": t,
                "ratings": ratings,
                "avg": statistics.fmean(scores) if scores else None,
                "min": min(scores, default=None),
                "max": max(scores, default=None),
                "points_100": 50 * statistics.fmean(scores) ** 0.3 if scores else None,
            }
        )
    hidden = wine.tastings.exclude(pk__in=[t["tasting"].pk for t in tastings])
    return render(
        request,
        "club/wine_detail.html",
        {"wine": wine, "tastings": tastings, "hidden_tastings": hidden},
    )


# --- Members ----------------------------------------------------------------------


def member_list(request):
    rows = stats.member_stats(stats.bottles())
    rows.sort(key=lambda r: (not r.member.active, -r.attended, r.member.display_name))
    return render(request, "club/member_list.html", {"rows": rows})


def member_detail(request, pk):
    member = get_object_or_404(Member, pk=pk)
    data = stats.bottles()
    summary = next(r for r in stats.member_stats(data) if r.member.pk == member.pk)
    purchases = sorted(
        (b for b in data if b.tasting.purchaser_id == member.pk),
        key=lambda b: b.tasting.session.date,
        reverse=True,
    )
    purchasers, raters, cells, diffs = stats.purchaser_rater_matrix()
    bias = [
        {
            "purchaser": p,
            "avg": cells[(p.pk, member.pk)][0],
            "n": cells[(p.pk, member.pk)][1],
            "diff": diffs[(p.pk, member.pk)],
        }
        for p in purchasers
        if (p.pk, member.pk) in cells and p.pk != member.pk
    ]
    bias.sort(key=lambda r: -r["diff"])
    hist_member = stats.rating_histogram(member)
    hist_club = stats.rating_histogram()
    keys = sorted(set(hist_member) | set(hist_club))
    total_m, total_c = sum(hist_member.values()) or 1, sum(hist_club.values()) or 1
    hist_chart = {
        "type": "bar",
        "data": {
            "labels": [f"{k:g}" for k in keys],
            "datasets": [
                {
                    "label": member.display_name,
                    "data": [round(100 * hist_member.get(k, 0) / total_m, 1) for k in keys],
                },
                {
                    "label": "Whole club",
                    "data": [round(100 * hist_club.get(k, 0) / total_c, 1) for k in keys],
                },
            ],
        },
        "options": {"scales": {"y": {"title": {"display": True, "text": "% of scores"}}}},
    }
    recent = (
        Rating.objects.visible()
        .filter(member=member)
        .select_related("tasting__wine", "tasting__session")
        .order_by("-tasting__session__date", "tasting__position")[:30]
    )
    return render(
        request,
        "club/member_detail.html",
        {
            "member": member,
            "s": summary,
            "purchases": purchases,
            "bias": bias,
            "hist_chart": hist_chart,
            "recent": recent,
        },
    )


# --- Leaderboards & analysis ------------------------------------------------------


def leaderboards(request):
    data = stats.bottles()
    ms = stats.member_stats(data)
    return render(
        request,
        "club/leaderboards.html",
        {
            "groups": stats.top_wine_groups(data, n=int(request.GET.get("n", 3))),
            "by_purchases": stats.ranked(ms, lambda r: r.avg_of_purchases),
            "by_difference": stats.ranked(ms, lambda r: r.purchase_difference),
            "by_contribution": stats.ranked(ms, lambda r: r.bottles_per_session),
            "by_generosity": stats.ranked(ms, lambda r: r.avg_given),
        },
    )


def analysis(request, dimension="varietal"):
    if dimension not in stats.DIMENSIONS:
        raise Http404
    data = stats.bottles()
    rows = stats.breakdown(data, dimension)
    title = stats.DIMENSIONS[dimension][0]
    chart_rows = rows if len(rows) <= 40 else [r for r in rows if r["n"] >= 2]
    chart = {
        "type": "bar",
        "data": {
            "labels": [r["label"] for r in chart_rows],
            "datasets": [
                {"label": "Average score", "data": [round(r["mean"], 3) for r in chart_rows]}
            ],
        },
        "options": {
            "indexAxis": "y" if len(chart_rows) > 12 else "x",
            "plugins": {"legend": {"display": False}},
            "scales": {"x": {"beginAtZero": False}, "y": {"beginAtZero": False}},
        },
        "counts": [r["n"] for r in chart_rows],
    }
    return render(
        request,
        "club/analysis.html",
        {
            "dimension": dimension,
            "title": title,
            "rows": rows,
            "chart": chart,
            "chart_height": max(300, 22 * len(chart_rows)) if len(chart_rows) > 12 else 320,
        },
    )


def price_analysis(request):
    data = [b for b in stats.bottles() if b.tasting.price]
    fit = stats.price_fit(data)
    points = [
        {"x": float(b.tasting.price), "y": round(b.avg, 3), "label": b.wine.full_name} for b in data
    ]
    datasets = [{"type": "scatter", "label": "Bottles", "data": points}]
    expected = []
    if fit:
        lo, hi = min(p["x"] for p in points), max(p["x"] for p in points)
        steps = 40
        curve = [lo * (hi / lo) ** (i / steps) for i in range(steps + 1)]
        datasets.append(
            {
                "type": "line",
                "label": "Fit: rating = a·ln(price) + b",
                "data": [{"x": round(x, 2), "y": round(fit.predict(x), 3)} for x in curve],
                "pointRadius": 0,
            }
        )
        expected = [(r / 2, fit.expected_price(r / 2)) for r in range(10, 20)]
    chart = {
        "type": "scatter",
        "data": {"datasets": datasets},
        "options": {
            "scales": {
                "x": {"type": "logarithmic", "title": {"display": True, "text": "Price ($)"}},
                "y": {"title": {"display": True, "text": "Average score"}},
            }
        },
    }
    return render(
        request,
        "club/price.html",
        {"fit": fit, "chart": chart, "expected": expected, "bands": stats.breakdown(data, "price")},
    )


def matrix(request):
    purchasers, raters, cells, diffs = stats.purchaser_rater_matrix()
    mode = request.GET.get("mode", "diff")
    rows = []
    for p in purchasers:
        row = []
        for r in raters:
            key = (p.pk, r.pk)
            if key in cells:
                avg, n = cells[key]
                row.append({"avg": avg, "n": n, "diff": diffs[key]})
            else:
                row.append(None)
        rows.append((p, row))
    return render(
        request,
        "club/matrix.html",
        {"raters": raters, "rows": rows, "mode": mode},
    )


def attendance(request):
    sessions = list(Session.objects.order_by("date"))
    members = list(Member.objects.all())
    present = defaultdict(set)
    for s_id, m_id in Attendance.objects.values_list("session_id", "member_id"):
        present[s_id].add(m_id)
    brought = defaultdict(set)
    for s_id, m_id in Tasting.objects.filter(purchaser__isnull=False).values_list(
        "session_id", "purchaser_id"
    ):
        brought[s_id].add(m_id)
    totals = Member.objects.annotate(n=Count("attendances")).values_list("pk", "n")
    totals = dict(totals)
    members = [m for m in members if totals.get(m.pk)]
    grid = [
        (
            s,
            [
                "P" if m.pk in brought[s.pk] else ("X" if m.pk in present[s.pk] else "")
                for m in members
            ],
        )
        for s in reversed(sessions)
    ]
    return render(
        request,
        "club/attendance.html",
        {
            "members": members,
            "grid": grid,
            "totals": [totals.get(m.pk, 0) for m in members],
            "rates": [totals.get(m.pk, 0) / (len(sessions) or 1) for m in members],
        },
    )


def export_xlsx(request):
    from .exporter import export_workbook

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    stamp = timezone.localdate().isoformat()
    response["Content-Disposition"] = f'attachment; filename="wine-club-{stamp}.xlsx"'
    export_workbook(response)
    return response
