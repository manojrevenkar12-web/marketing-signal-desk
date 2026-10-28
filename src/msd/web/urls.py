from django.contrib.auth import views as auth
from django.urls import path

from msd.web import views

urlpatterns = [
    path("healthz", views.health, name="health"),
    path("login/", auth.LoginView.as_view(template_name="web/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", views.home, name="home"),
    path("w/<slug:slug>/", views.overview, name="overview"),
    path("w/<slug:slug>/overview/diagnosis", views.overview_diagnosis, name="overview_diagnosis"),
    path("w/<slug:slug>/ask", views.ask, name="ask"),
    path("w/<slug:slug>/questions/<int:pk>", views.question, name="question"),
    path("w/<slug:slug>/questions/<int:pk>/retry", views.retry_question, name="retry_question"),
    path("w/<slug:slug>/proposals", views.proposals, name="proposals"),
    path("w/<slug:slug>/proposals/<int:pk>/decide", views.decide, name="decide"),
    path("w/<slug:slug>/checks", views.checks, name="checks"),
    path("w/<slug:slug>/connections", views.connections, name="connections"),
    path("w/<slug:slug>/connections/<int:pk>/sync", views.sync_now, name="sync_now"),
    path("w/<slug:slug>/audit", views.audit, name="audit"),
]
