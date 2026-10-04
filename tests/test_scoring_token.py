from decimal import Decimal

import pytest
from django.urls import reverse

from club.models import Attendance, Rating, Session
from club.scoring_tokens import TOKEN_PATTERN, normalise_token


def token_rate(client, token, tasting, **data):
    url = reverse("token_rate", args=[token, tasting.pk])
    return client.post(url, data, HTTP_HX_REQUEST="true")


@pytest.fixture
def token(open_session):
    session = open_session["session"]
    session.refresh_from_db()
    return session.scoring_token


def test_opening_issues_token_and_closing_revokes_it(client, organiser, open_session):
    session = open_session["session"]
    client.force_login(organiser)
    url = reverse("session_status", args=[1])

    client.post(url, {"action": "plan"})
    session.refresh_from_db()
    assert session.scoring_token is None

    client.post(url, {"action": "open"})
    session.refresh_from_db()
    first = session.scoring_token
    assert TOKEN_PATTERN.fullmatch(first)

    client.post(url, {"action": "reveal"})  # other status changes keep the code
    session.refresh_from_db()
    assert session.scoring_token == first

    client.post(url, {"action": "close"})
    session.refresh_from_db()
    assert session.scoring_token is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("ab12cd", "AB12CD"), (" AB1-2CD ", "AB12CD"), ("AB12C", None), ("AB12C!", None), ("", None)],
)
def test_normalise_token(raw, expected):
    assert normalise_token(raw) == expected


def test_session_page_shows_code_and_qr_while_open(client, organiser, open_session, token):
    client.force_login(organiser)
    page = client.get(reverse("session_detail", args=[1])).content.decode()
    assert token in page and 'class="qr"' in page
    assert client.get(reverse("session_qr", args=[1])).status_code == 200

    Session.objects.filter(pk=open_session["session"].pk).update(status=Session.Status.CLOSED)
    page = client.get(reverse("session_detail", args=[1])).content.decode()
    assert token not in page
    assert client.get(reverse("session_qr", args=[1])).status_code == 302


def test_code_entry_redirects_to_scoring_page(client, token):
    resp = client.get(reverse("scoring_code"), {"code": token.lower()})
    assert resp.status_code == 302
    assert resp.url == reverse("token_score", args=[token])
    assert client.get(reverse("scoring_code"), {"code": "ZZZZZZ"}).status_code == 404


def test_anonymous_picks_member_and_scores(client, open_session, token):
    t, bob = open_session["tasting"], open_session["bob"]
    page = client.get(reverse("token_score", args=[token])).content.decode()
    assert "Choose yourself" in page and "Bob" in page

    page = client.get(reverse("token_score", args=[token]), {"member": bob.pk}).content.decode()
    assert t.wine.full_name in page
    assert reverse("token_rate", args=[token, t.pk]) in page

    assert token_rate(client, token, t, member=bob.pk, score="8.5").status_code == 200
    rating = Rating.objects.get(tasting=t, member=bob)
    assert rating.score == Decimal("8.5") and rating.entered_by is None
    assert Attendance.objects.filter(session=t.session, member=bob).exists()

    # The choice is remembered for the next visit with the same code.
    page = client.get(reverse("token_score", args=[token])).content.decode()
    assert "Choose yourself" not in page and "8.5" in page


def test_token_rating_requires_member(client, open_session, token):
    resp = token_rate(client, token, open_session["tasting"], score="8")
    assert resp.status_code == 400
    assert not Rating.objects.exists()


def test_closed_session_rejects_code(client, open_session, token):
    Session.objects.filter(pk=open_session["session"].pk).update(status=Session.Status.CLOSED)
    assert client.get(reverse("token_score", args=[token])).status_code == 404
    bob = open_session["bob"]
    assert (
        token_rate(client, token, open_session["tasting"], member=bob.pk, score="8").status_code
        == 403
    )
    assert not Rating.objects.exists()


def test_code_only_reaches_its_own_session(client, organiser, open_session, token):
    other = Session.objects.create(
        number=2, date="2026-10-09", era=open_session["session"].era, status=Session.Status.OPEN
    )
    assert other.scoring_token and other.scoring_token != token
    client.force_login(organiser)
    elsewhere = client.post(
        reverse("tasting_create", args=[2]), {"wine_name": "Penfolds 2018 Bin 389", "position": 1}
    )
    assert elsewhere.status_code == 302
    client.logout()
    tasting = other.tastings.get()
    resp = token_rate(client, token, tasting, member=open_session["bob"].pk, score="8")
    assert resp.status_code == 400
    assert not Rating.objects.exists()
