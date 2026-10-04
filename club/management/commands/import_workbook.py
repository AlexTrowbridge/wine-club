from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from club.importer import import_workbook


class Command(BaseCommand):
    help = "Import (or re-import) the legacy 'Wine Club.xlsx' workbook."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument(
            "--review-csv",
            type=Path,
            default=Path("import_review.csv"),
            help="Where to write wines that need manual review (default: %(default)s).",
        )

    def handle(self, path, review_csv, **options):
        if not path.exists():
            raise CommandError(f"{path} does not exist")
        report = import_workbook(path)

        self.stdout.write(
            f"Members: {report.members}  Sessions: {report.sessions}  "
            f"Wines: {report.wines} new  Tastings: {report.tastings}  "
            f"Ratings: {report.ratings}  Attendances: {report.attendances}"
        )
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
