import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User

from club.importer import import_workbook
from club.models import Era, Member, Session, Tasting
from club.permissions import ORGANISER_GROUP
from club.services import get_or_create_wine

from .workbook import MEMBERS, SAMPLE, build_workbook


@pytest.fixture
def sample_workbook(tmp_path):
    path = tmp_path / "club.xlsx"
    build_workbook(path, MEMBERS, SAMPLE)
    return path


@pytest.fixture
def imported(db, sample_workbook):
    return import_workbook(sample_workbook)


@pytest.fixture
def organiser(db):
    user = User.objects.create_user("org", password="pw")
    user.groups.add(Group.objects.get(name=ORGANISER_GROUP))
    return user


@pytest.fixture
def open_session(db):
    """An open session with two members (linked to logins) and one bottle."""
    era = Era.objects.create(name="Era", start_date=dt.date(2026, 1, 1))
    session = Session.objects.create(
        number=1, date=dt.date(2026, 10, 2), era=era, status=Session.Status.OPEN
    )
    alice = Member.objects.create(
        display_name="Alice", user=User.objects.create_user("alice", password="pw")
    )
    bob = Member.objects.create(
        display_name="Bob", user=User.objects.create_user("bob", password="pw")
    )
    wine, _ = get_or_create_wine("Yangarra 2021 Old Vine Grenache")
    tasting = Tasting.objects.create(
        session=session, wine=wine, position=1, purchaser=alice, price=Decimal("40")
    )
    return {"session": session, "alice": alice, "bob": bob, "tasting": tasting}
