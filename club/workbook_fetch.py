"""Download the live club workbook from a Box shared link.

Box share pages (``https://<x>.box.com/s/<token>``) are HTML; the same token under
``/shared/static/<token>.xlsx`` serves the file itself without a login, provided the
link is shared with "people with the link".
"""

import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HOST_SUFFIX = ".box.com"
SHARE_PATH_RE = re.compile(r"^/(?:s|shared/static)/(?P<token>[A-Za-z0-9]+)(?:\.xlsx)?/?$")
STATIC_PATH = "/shared/static/{token}.xlsx"
FETCH_TIMEOUT_S = 30
CHUNK_BYTES = 64 * 1024
MAX_BYTES = 20 * 1024 * 1024
XLSX_MAGIC = b"PK\x03\x04"  # .xlsx files are zip archives
USER_AGENT = "wine-club-importer"


class WorkbookFetchError(Exception):
    """The workbook couldn't be downloaded; the message is safe to show to organisers."""


def box_download_url(share_url: str) -> str:
    """Turn a Box shared link into its direct-download form."""
    parts = urlsplit(share_url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise WorkbookFetchError("The workbook link must start with https://")
    if not host.endswith(ALLOWED_HOST_SUFFIX):
        raise WorkbookFetchError(f"The workbook link must be a Box link (*{ALLOWED_HOST_SUFFIX})")
    match = SHARE_PATH_RE.match(parts.path)
    if match is None:
        raise WorkbookFetchError("Unrecognised Box link; expected https://<x>.box.com/s/<token>")
    return f"https://{host}{STATIC_PATH.format(token=match['token'])}"


def _read_capped(response) -> bytes:
    data = bytearray()
    while chunk := response.read(CHUNK_BYTES):
        data += chunk
        if len(data) > MAX_BYTES:
            raise WorkbookFetchError(f"The workbook is larger than {MAX_BYTES // 2**20} MB")
    return bytes(data)


def fetch_workbook_bytes(share_url: str) -> bytes:
    request = urllib.request.Request(
        box_download_url(share_url), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            data = _read_capped(response)
    except urllib.error.HTTPError as exc:
        raise WorkbookFetchError(
            f"Box returned HTTP {exc.code}; check the link is shared with 'people with the link'"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise WorkbookFetchError(f"Couldn't reach Box: {exc}") from exc
    if not data.startswith(XLSX_MAGIC):
        raise WorkbookFetchError(
            "Box didn't return a spreadsheet (the link may need a login or have been removed)"
        )
    return data


def download_workbook(share_url: str) -> Path:
    """Download to a temporary .xlsx file (under /tmp); the caller deletes it."""
    data = fetch_workbook_bytes(share_url)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as fh:
        fh.write(data)
    return Path(fh.name)
