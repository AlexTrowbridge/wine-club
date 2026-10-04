from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Wine Club admin"
admin.site.site_title = "Wine Club"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("club.urls")),
]
