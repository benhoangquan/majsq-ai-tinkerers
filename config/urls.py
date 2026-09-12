from django.urls import path

from majsq_bot import views


urlpatterns = [
    path("telegram/webhook/", views.telegram_webhook, name="telegram-webhook"),
    path("api/picks/<str:share_id>/", views.pickset_detail, name="pickset-detail"),
    path("api/connect/callback/", views.connect_callback, name="connect-callback"),
]

