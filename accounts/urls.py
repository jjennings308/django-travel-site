# accounts/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    # login/logout (Django built-ins)
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # your existing admin-only user add
    path("user/add/", views.user_add, name="user-add"),

    # self signup + activation
    path("signup/", views.signup, name="signup"),
    path("activate/<uidb64>/<token>/", views.activate, name="activate"),
]
