from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from club.importer import import_workbook
from club.workbook_fetch import WorkbookFetchError, download_workbook

URL_PREFIX = "https://"


class Command(BaseCommand):
    help = "Import (or re-import) the 'Wine Club.xlsx' workbook from a file or Box shared link."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the .xlsx, or a Box shared link.")
        parser.add_argument(
            "--review-csv",
            type=Path,
            default=Path("import_review.csv"),
            help="Where to write wines that need manual review (default: %(default)s).",
        )

    def handle(self, path, review_csv, **options):
        if not path.startswith(URL_PREFIX):
            report = self._import_file(Path(path))
        else:
            try:
                downloaded = download_workbook(path)
            except WorkbookFetchError as exc:
                raise CommandError(str(exc)) from exc
            try:
                report = self._import_file(downloaded)
            finally:
                downloaded.unlink(missing_ok=True)
        self._print_report(report, review_csv)

    def _import_file(self, path):
        if not path.exists():
            raise CommandError(f"{path} does not exist")
        return import_workbook(path)

    def _print_report(self, report, review_csv):
        self.stdout.write(report.counts_line())
        for label, ok, detail in report.checks:
            style = self.style.SUCCESS if ok else self.style.WARNING
            self.stdout.write(style(f"[{'ok' if ok else '!!'}] {label}"))
            if detail:
                self.stdout.write(f"     {detail}")
        for error in report.errors:
            self.stderr.write(self.style.ERROR(error))
        if report.review:
            report.write_review_csv(review_csv)
            self.stdout.write(f"{len(report.review)} item(s) to review written to {review_csv}")
        if report.errors:
            raise CommandError(f"{len(report.errors)} error(s); see above")
