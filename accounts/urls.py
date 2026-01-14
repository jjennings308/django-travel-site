# accounts/urls.py
from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Registration & Email Verification
    path('register/', views.register, name='register'),
    path('registration-complete/', views.registration_complete, name='registration_complete'),
    # Use re_path to properly capture the token with special characters
    re_path(
    r'^verify-email/(?P<uidb64>[0-9A-Za-z_\-=]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,32})/$',
    views.verify_email,
    name='verify_email'
    ),
    path(
        'resend-verification/',
        views.resend_verification,
        name='resend_verification'
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
        template_name='accounts/password_reset.html',
        email_template_name='accounts/emails/password_reset_email.html',
        subject_template_name='accounts/emails/password_reset_subject.txt'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html'
    ), name='password_reset_complete'),
    
    # Admin Account Management
    path('admin/accounts/', views.admin_account_list, name='admin_account_list'),
    path('admin/accounts/<int:user_id>/', views.admin_account_detail, name='admin_account_detail'),
    path('admin/accounts/<int:user_id>/toggle-status/', views.admin_toggle_user_status, name='admin_toggle_user_status'),
    #path("tz/set/", views.set_timezone, name="set-timezone"),
]  

