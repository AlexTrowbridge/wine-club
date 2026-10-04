from pathlib import Path

from django.core.management.base import BaseCommand

from club.exporter import export_workbook


class Command(BaseCommand):
    help = "Export all data to an .xlsx laid out like the original 'Wine Club.xlsx'."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)

    def handle(self, path, **options):
        with open(path, "wb") as fh:
            export_workbook(fh)
        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
