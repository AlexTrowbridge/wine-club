from decimal import Decimal

import pytest
from django.urls import reverse

from club import stats
from club.models import Attendance, Rating, Session


def rate(client, tasting, **data):
    return client.post(reverse("rate", args=[tasting.pk]), data, HTTP_HX_REQUEST="true")


@pytest.fixture
def alice_client(client, open_session):
    client.login(username="alice", password="pw")
    return client


def test_member_scores_own_wine_and_attendance_is_recorded(alice_client, open_session):
    t, alice = open_session["tasting"], open_session["alice"]
    assert rate(alice_client, t, score="7.5").status_code == 200
    assert Rating.objects.get(tasting=t, member=alice).score == Decimal("7.5")
    assert Attendance.objects.filter(session=t.session, member=alice).exists()

    rate(alice_client, t, score="x")
    assert Rating.objects.get(tasting=t, member=alice).score is None
    rate(alice_client, t, score="")
    assert not Rating.objects.filter(tasting=t, member=alice).exists()


@pytest.mark.parametrize("bad", ["11", "7.3", "-1", "abc", "nan", "inf"])
def test_invalid_scores_rejected(alice_client, open_session, bad):
    assert rate(alice_client, open_session["tasting"], score=bad).status_code == 400
    assert not Rating.objects.exists()


def test_member_cannot_score_for_someone_else(alice_client, open_session):
    resp = rate(alice_client, open_session["tasting"], score="8", member=open_session["bob"].pk)
    assert resp.status_code == 403
    assert not Rating.objects.exists()


def test_member_cannot_score_closed_session(alice_client, open_session):
    Session.objects.update(status=Session.Status.CLOSED)
    assert rate(alice_client, open_session["tasting"], score="8").status_code == 403


def test_organiser_can_score_for_anyone_any_time(client, organiser, open_session):
    Session.objects.update(status=Session.Status.CLOSED)
    client.force_login(organiser)
    t, bob = open_session["tasting"], open_session["bob"]
    resp = rate(client, t, score="6", member=bob.pk, ui="grid")
    assert resp.status_code == 200
    assert b"cell-saved" in resp.content
    rating = Rating.objects.get(tasting=t, member=bob)
    assert rating.score == 6 and rating.entered_by == organiser


def test_scores_hidden_until_revealed(client, open_session):
    t, alice, bob = open_session["tasting"], open_session["alice"], open_session["bob"]
    Rating.objects.create(tasting=t, member=alice, score=9)
    Rating.objects.create(tasting=t, member=bob, score=4)

    client.login(username="bob", password="pw")
    page = client.get(reverse("session_detail", args=[1])).content.decode()
    assert 'title="Scored (hidden until revealed)"' in page  # Alice's score is masked
    assert stats.bottles() == []  # and kept out of every statistic

    Session.objects.update(scores_revealed=True)
    page = client.get(reverse("session_detail", args=[1])).content.decode()
    assert "hidden until revealed" not in page
    assert len(stats.bottles()) == 1


def test_only_organisers_manage_sessions(alice_client, open_session):
    url = reverse("session_status", args=[1])
    assert alice_client.post(url, {"action": "close"}).status_code == 403
    assert alice_client.get(reverse("tasting_create", args=[1])).status_code == 403


def test_organiser_adds_bottle_with_new_wine(client, organiser, open_session):
    client.force_login(organiser)
    resp = client.post(
        reverse("tasting_create", args=[1]),
        {
            "wine_name": "Kay Brothers 2019 Basket Pressed Grenache",
            "region": "McLaren Vale",
            "country": "Australia",
            "position": 2,
            "purchaser": open_session["bob"].pk,
            "price": "30",
        },
    )
    assert resp.status_code == 302
    t = open_session["session"].tastings.get(position=2)
    assert t.wine.producer == "Kay Brothers"
    assert [v.name for v in t.wine.varietals.all()] == ["Grenache"]
    assert t.wine.region.name == "McLaren Vale"
    assert Attendance.objects.filter(session=t.session, member=open_session["bob"]).exists()


def test_login_required_except_health(client, db):
    assert client.get(reverse("wine_list")).status_code == 302
    assert client.get(reverse("healthz")).status_code == 200
    assert client.get(reverse("readyz")).status_code == 200
