from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import models
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from .models import (
    Attendance,
    Country,
    Era,
    Member,
    Rating,
    Region,
    Session,
    Tasting,
    Varietal,
    Wine,
    WineVarietal,
    WorkbookSource,
)
from .workbook_sync import run_remote_import


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ["display_name", "user", "active", "joined", "sort_order"]
    list_editable = ["active", "sort_order"]
    list_filter = ["active"]
    search_fields = ["display_name", "user__username", "user__email"]
    autocomplete_fields = ["user"]


@admin.register(Era)
class EraAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date"]


class TastingInline(admin.TabularInline):
    model = Tasting
    extra = 0
    autocomplete_fields = ["wine", "purchaser"]
    fields = ["position", "wine", "purchaser", "shared_purchase", "price"]


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ["number", "date", "theme", "era", "status", "scores_revealed"]
    readonly_fields = ["scoring_token"]
    list_filter = ["era", "status"]
    search_fields = ["theme"]
    date_hierarchy = "date"
    inlines = [TastingInline]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["session", "member"]
    list_filter = ["member"]
    autocomplete_fields = ["session", "member"]


class RegionInline(admin.TabularInline):
    model = Region
    extra = 0


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    inlines = [RegionInline]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "country"]
    list_filter = ["country"]
    search_fields = ["name", "country__name"]


@admin.register(Varietal)
class VarietalAdmin(admin.ModelAdmin):
    list_display = ["name", "aliases"]
    search_fields = ["name", "aliases"]


class WineVarietalInline(admin.TabularInline):
    model = WineVarietal
    extra = 1
    autocomplete_fields = ["varietal"]


@admin.register(Wine)
class WineAdmin(admin.ModelAdmin):
    list_display = ["full_name", "producer", "vintage", "region", "style", "is_blend", "jh_score"]
    list_filter = ["style", "is_blend", "region__country"]
    search_fields = ["full_name", "producer", "cuvee"]
    autocomplete_fields = ["region"]
    inlines = [WineVarietalInline]


class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0
    autocomplete_fields = ["member"]
    fields = ["member", "score", "entered_by", "updated"]
    readonly_fields = ["entered_by", "updated"]


@admin.register(Tasting)
class TastingAdmin(admin.ModelAdmin):
    list_display = ["wine", "session", "position", "purchaser_label", "price"]
    list_filter = ["session__era", "purchaser"]
    search_fields = ["wine__full_name"]
    autocomplete_fields = ["wine", "session", "purchaser"]
    inlines = [RatingInline]


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ["tasting", "member", "score", "entered_by", "updated"]
    list_filter = ["member", "tasting__session__era"]
    search_fields = ["tasting__wine__full_name", "member__display_name"]
    autocomplete_fields = ["tasting", "member"]
    readonly_fields = ["entered_by", "created", "updated"]


@admin.register(WorkbookSource)
class WorkbookSourceAdmin(admin.ModelAdmin):
    fields = ["url", "last_imported_at", "last_imported_by", "last_ok"]
    readonly_fields = ["last_imported_at", "last_imported_by", "last_ok"]
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}

    def has_add_permission(self, request):
        return False  # the single row is created on first visit

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        source = WorkbookSource.load()
        return redirect("admin:club_workbooksource_change", source.pk)

    def get_urls(self):
        import_url = path(
            "<int:pk>/import/",
            self.admin_site.admin_view(self.import_view),
            name="club_workbooksource_import",
        )
        return [import_url, *super().get_urls()]

    def import_view(self, request, pk):
        return require_POST(self._run_import)(request, pk)

    def _run_import(self, request, pk):
        source = get_object_or_404(WorkbookSource, pk=pk)
        if not self.has_change_permission(request, source):
            raise PermissionDenied
        report = run_remote_import(request.user)
        if report.errors:
            messages.error(request, "Import failed; nothing was changed. " + report.errors[0])
        elif not report.ok:
            messages.warning(request, f"Imported with warnings. {report.counts_line()}")
        else:
            messages.success(request, f"Imported. {report.counts_line()}")
        return redirect(reverse("admin:club_workbooksource_change", args=[source.pk]))
