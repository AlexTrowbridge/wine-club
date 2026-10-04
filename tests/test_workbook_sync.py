import io
import urllib.error

import openpyxl
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from club import workbook_fetch
from club.models import Member, Session, Tasting, WorkbookSource
from club.workbook_fetch import WorkbookFetchError, box_download_url, fetch_workbook_bytes

from .workbook import MEMBERS, SAMPLE, build_workbook

SHARE_URL = "https://example.box.com/s/abc123"
STATIC_URL = "https://example.box.com/shared/static/abc123.xlsx"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def workbook_bytes(tmp_path):
    path = tmp_path / "club.xlsx"
    build_workbook(path, MEMBERS, SAMPLE)
    return path.read_bytes()


@pytest.fixture
def serve(monkeypatch):
    """Make urlopen return the given bytes (or raise the given exception)."""
    requested = []

    def install(payload):
        def fake_urlopen(request, timeout):
            requested.append(request.full_url)
            if isinstance(payload, Exception):
                raise payload
            return FakeResponse(payload)

        monkeypatch.setattr(workbook_fetch.urllib.request, "urlopen", fake_urlopen)
        return requested

    return install


@pytest.fixture
def admin_client(client, db):
    client.force_login(User.objects.create_superuser("boss", password="pw"))
    return client


@pytest.fixture
def source(db):
    source = WorkbookSource.load()
    source.url = SHARE_URL
    source.save()
    return source


def import_url(source):
    return reverse("admin:club_workbooksource_import", args=[source.pk])


@pytest.mark.parametrize(
    "url",
    [SHARE_URL, STATIC_URL, "https://example.box.com/shared/static/abc123", SHARE_URL + "/"],
)
def test_box_download_url(url):
    assert box_download_url(url) == STATIC_URL


@pytest.mark.parametrize(
    "url",
    [
        "http://example.box.com/s/abc123",
        "https://example.com/s/abc123",
        "https://box.com.evil.test/s/abc123",
        "https://10.0.0.1/s/abc123",
        "https://example.box.com/folder/123",
    ],
)
def test_box_download_url_rejects(url):
    with pytest.raises(WorkbookFetchError):
        box_download_url(url)


def test_fetch_downloads_static_url(serve, workbook_bytes):
    requested = serve(workbook_bytes)
    assert fetch_workbook_bytes(SHARE_URL) == workbook_bytes
    assert requested == [STATIC_URL]


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"<html>Please log in</html>", "didn't return a spreadsheet"),
        (urllib.error.URLError("no route"), "Couldn't reach Box"),
        (urllib.error.HTTPError(STATIC_URL, 404, "Not Found", {}, None), "HTTP 404"),
    ],
)
def test_fetch_errors(serve, payload, message):
    serve(payload)
    with pytest.raises(WorkbookFetchError, match=message):
        fetch_workbook_bytes(SHARE_URL)


def test_fetch_rejects_oversized(serve, monkeypatch, workbook_bytes):
    monkeypatch.setattr(workbook_fetch, "MAX_BYTES", 100)
    serve(workbook_bytes)
    with pytest.raises(WorkbookFetchError, match="larger than"):
        fetch_workbook_bytes(SHARE_URL)


def test_admin_import(admin_client, source, serve, workbook_bytes):
    serve(workbook_bytes)
    response = admin_client.post(import_url(source), follow=True)
    assert response.status_code == 200
    assert Tasting.objects.count() == 4
    source.refresh_from_db()
    assert source.last_ok is True
    assert source.last_imported_by.username == "boss"
    assert "Tastings: 4" in source.last_summary
    assert "Imported" in response.content.decode()


def test_admin_page_renders(admin_client, source):
    response = admin_client.get(reverse("admin:club_workbooksource_changelist"), follow=True)
    assert response.status_code == 200
    assert "Import now" in response.content.decode()


def test_admin_import_requires_post(admin_client, source):
    assert admin_client.get(import_url(source)).status_code == 405


def test_import_forbidden_without_permission(client, source, serve, workbook_bytes):
    serve(workbook_bytes)
    user = User.objects.create_user("staff", password="pw", is_staff=True)
    client.force_login(user)
    assert client.post(import_url(source)).status_code == 403
    assert not Tasting.objects.exists()


def test_failed_download_changes_nothing(admin_client, source, serve):
    serve(b"<html>removed</html>")
    response = admin_client.post(import_url(source), follow=True)
    assert "nothing was changed" in response.content.decode()
    assert not Member.objects.exists()
    source.refresh_from_db()
    assert source.last_ok is False


def test_import_errors_roll_back(admin_client, source, serve, tmp_path):
    path = tmp_path / "broken.xlsx"
    build_workbook(path, MEMBERS, SAMPLE)
    # Blank a bottle's date (row 4 = first bottle) so its session can't be found: the
    # importer reports an error rather than raising, and everything must roll back.
    wb = openpyxl.load_workbook(path)
    wb["Raw Ratings"]["C4"] = None
    wb.save(path)
    serve(path.read_bytes())
    admin_client.post(import_url(source))
    assert not Member.objects.exists()
    source.refresh_from_db()
    assert source.last_ok is False
    assert "no session" in source.last_summary


def test_reimport_keeps_open_session_open(admin_client, source, serve, workbook_bytes):
    serve(workbook_bytes)
    admin_client.post(import_url(source))
    session = Session.objects.order_by("-number").first()
    session.status = Session.Status.OPEN
    session.scores_revealed = False
    session.save()

    admin_client.post(import_url(source))
    session.refresh_from_db()
    assert session.status == Session.Status.OPEN
    assert not session.scores_revealed
    source.refresh_from_db()
    assert f"#{session.number} is still open or planned" in source.last_summary
