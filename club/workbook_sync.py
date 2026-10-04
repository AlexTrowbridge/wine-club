"""Re-import the live club workbook from the link saved in the admin."""

import logging

from django.utils import timezone

from .importer import ImportReport, import_workbook_or_rollback
from .models import WorkbookSource
from .workbook_fetch import WorkbookFetchError, download_workbook

logger = logging.getLogger(__name__)


def _import_from_url(url: str) -> ImportReport:
    try:
        path = download_workbook(url)
    except WorkbookFetchError as exc:
        report = ImportReport()
        report.errors.append(str(exc))
        return report
    try:
        return import_workbook_or_rollback(path)
    finally:
        path.unlink(missing_ok=True)


def _record_result(source: WorkbookSource, user, report: ImportReport):
    source.last_imported_at = timezone.now()
    source.last_imported_by = user
    source.last_ok = not report.errors  # failed checks are warnings; data was saved
    source.last_summary = report.summary_text()
    source.save(update_fields=["last_imported_at", "last_imported_by", "last_ok", "last_summary"])


def run_remote_import(user) -> ImportReport:
    """Download and import the workbook, recording the outcome on ``WorkbookSource``.

    The import is all or nothing: on any error the database is left unchanged.
    """
    source = WorkbookSource.load()
    if not source.url:
        report = ImportReport()
        report.errors.append("No workbook link saved yet")
        return report
    report = _import_from_url(source.url)
    if report.errors:
        logger.warning("Workbook import failed: %s", "; ".join(report.errors))
    _record_result(source, user, report)
    return report
