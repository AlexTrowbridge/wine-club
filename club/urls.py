from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("healthz", views.healthz, name="healthz"),
    path("readyz", views.readyz, name="readyz"),
    path("sessions/", views.session_list, name="session_list"),
    path("sessions/new/", views.session_edit, name="session_create"),
    path("sessions/<int:number>/", views.session_detail, name="session_detail"),
    path("sessions/<int:number>/edit/", views.session_edit, name="session_edit"),
    path("sessions/<int:number>/status/", views.session_status, name="session_status"),
    path("sessions/<int:number>/attendance/", views.session_attendance, name="session_attendance"),
    path("sessions/<int:number>/score/", views.session_score, name="session_score"),
    path("sessions/<int:number>/bottles/new/", views.tasting_edit, name="tasting_create"),
    path("sessions/<int:number>/bottles/<int:pk>/", views.tasting_edit, name="tasting_edit"),
    path("bottles/<int:pk>/rate/", views.rate, name="rate"),
    path("wines/", views.wine_list, name="wine_list"),
    path("wines/<int:pk>/", views.wine_detail, name="wine_detail"),
    path("members/", views.member_list, name="member_list"),
    path("members/<int:pk>/", views.member_detail, name="member_detail"),
    path("attendance/", views.attendance, name="attendance"),
    path("leaderboards/", views.leaderboards, name="leaderboards"),
    path("analysis/price-vs-rating/", views.price_analysis, name="price_analysis"),
    path("analysis/purchaser-vs-rater/", views.matrix, name="matrix"),
    path("analysis/", views.analysis, name="analysis"),
    path("analysis/<slug:dimension>/", views.analysis, name="analysis"),
    path("export.xlsx", views.export_xlsx, name="export_xlsx"),
]
