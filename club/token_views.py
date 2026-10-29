"""Scoring with a session's code (from its QR code), without logging in.

Anyone holding the code of an open session picks themselves from the member list and
scores that session's wines. The code stops working as soon as the session leaves the
open state.
"""

from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import SCORE_CHOICES, ScoreForm
from .models import Member, Rating, Session, Tasting
from .permissions import can_see_scores, member_for
from .scoring_tokens import normalise_token
from .services import save_score
from .views import render_score_item

# Django session key remembering who this browser last scored as: {"token", "member"}.
CHOSEN_MEMBER_KEY = "scoring_member"
# Django session key listing whom this browser has scored as: {"token", "members"}.
# Only they (or someone allowed to see everyone's scores) see those members' saved scores.
SCORED_AS_KEY = "scored_as"
UNKNOWN_CODE = "That code isn't valid, or scoring for its session has closed."


@login_not_required
def scoring_code(request):
    """Type in a session's code, for people who can't scan the QR code."""
    raw = request.GET.get("code")
    if raw is None:
        return render(request, "club/scoring_code.html")
    token = normalise_token(raw)
    if token and Session.objects.open_with_token(token):
        return redirect("token_score", token=token)
    return render_unknown_code(request, raw)


@login_not_required
def token_score(request, token):
    session = open_session_or_none(token)
    if session is None:
        return render_unknown_code(request, token)
    members = Member.objects.filter(active=True)
    member = chosen_member(request, session, members)
    if member:
        remember_member(request, session, member)
    return render(
        request,
        "club/token_score.html",
        {
            "session": session,
            "token": session.scoring_token,
            "members": members,
            "member": member,
            "items": score_items(session, member, may_see_scores_of(request, session, member)),
            "choices": SCORE_CHOICES,
        },
    )


@login_not_required
@require_POST
def token_rate(request, token, pk):
    session = open_session_or_none(token)
    if session is None:
        return HttpResponse(UNKNOWN_CODE, status=403)
    tasting = get_object_or_404(Tasting.objects.select_related("session", "wine"), pk=pk)
    if tasting.session_id != session.pk:
        return HttpResponseBadRequest("That wine isn't in this session.")
    form = ScoreForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest(" ".join(form.non_field_errors()) or "Invalid score")
    member = form.cleaned_data["member"]
    if member is None or not member.active:
        return HttpResponseBadRequest("Choose who you are first.")
    entered_by = request.user if request.user.is_authenticated else None
    rating = save_score(tasting, member, form.cleaned_data, entered_by)
    record_scored_as(request, session, member)
    return render_score_item(request, tasting, member, rating, token=session.scoring_token)


def open_session_or_none(raw_token):
    token = normalise_token(raw_token)
    return Session.objects.open_with_token(token) if token else None


def render_unknown_code(request, raw):
    return render(
        request, "club/scoring_code.html", {"error": UNKNOWN_CODE, "code": raw}, status=404
    )


def chosen_member(request, session, members):
    """Who is scoring: the dropdown choice, else this browser's last choice, else the login."""
    if picked := request.GET.get("member"):
        return members.filter(pk=picked).first() if picked.isdigit() else None
    remembered = request.session.get(CHOSEN_MEMBER_KEY) or {}
    if remembered.get("token") == session.scoring_token:
        return members.filter(pk=remembered.get("member")).first()
    own = member_for(request.user)
    return own if own and own.active else None


def remember_member(request, session, member):
    request.session[CHOSEN_MEMBER_KEY] = {"token": session.scoring_token, "member": member.pk}


def record_scored_as(request, session, member):
    scored = request.session.get(SCORED_AS_KEY) or {}
    members = scored.get("members", []) if scored.get("token") == session.scoring_token else []
    if member.pk not in members:
        members = [*members, member.pk]
    request.session[SCORED_AS_KEY] = {"token": session.scoring_token, "members": members}


def may_see_scores_of(request, session, member):
    """Whether this visitor may see ``member``'s saved scores on the code-based page.

    Anyone with the code can pick any name, so picking a name alone doesn't reveal
    that member's scores before the organiser reveals them.
    """
    if member is None or can_see_scores(request.user, session):
        return True
    own = member_for(request.user)
    if own is not None and own.pk == member.pk:
        return True
    scored = request.session.get(SCORED_AS_KEY) or {}
    return scored.get("token") == session.scoring_token and member.pk in scored.get("members", [])


def score_items(session, member, show_scores):
    """Scoring cards for ``member``; without ``show_scores``, saved scores are only flagged."""
    if member is None:
        return []
    mine = {r.tasting_id: r for r in Rating.objects.filter(tasting__session=session, member=member)}
    items = []
    for t in session.tastings.select_related("wine", "purchaser"):
        rating = mine.get(t.pk)
        items.append(
            {
                "tasting": t,
                "rating": rating if show_scores else None,
                "hidden_rating": rating is not None and not show_scores,
                "can_rate": True,
            }
        )
    return items
