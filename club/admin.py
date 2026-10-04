from django.contrib import admin

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
)


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
