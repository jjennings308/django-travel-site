# accounts/urls.py
from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Registration & Email Verification
    path('register/', views.register, name='register'),
    path('registration-complete/', views.registration_complete, name='registration_complete'),
    re_path(
        r'^verify-email/(?P<uidb64>[0-9A-Za-z_\-=]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,32})/$',
        views.verify_email,
        name='verify_email'
    ),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    
    # Authentication
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html',
        redirect_authenticated_user=True
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(
        next_page='login'
    ), name='logout'),
    
    # Password Reset
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset.html",
        email_template_name="accounts/emails/password_reset_email.txt",
        html_email_template_name="accounts/emails/password_reset_email.html",
        subject_template_name="accounts/emails/password_reset_subject.txt",
    ), name="password_reset"),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url='/accounts/reset/done/'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html'
    ), name='password_reset_complete'),
    
    # Profile & Settings Management
    path("theme/set/", views.set_theme, name="set_theme"),
    path("tz/set/", views.set_timezone, name="set_timezone"),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('travel-preferences/', views.edit_travel_preferences, name='edit_travel_preferences'),
    path('settings/', views.settings_view, name='settings'),
    path('profile/<str:username>/', views.profile_view, name='profile_view'),
    
    # Role Requests
    path('request-role/', views.request_role, name='request_role'),
    path('role-request-status/', views.role_request_status, name='role_request_status'),
]
