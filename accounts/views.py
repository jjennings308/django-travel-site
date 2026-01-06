# accounts/view.py
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms import AdminUserCreateForm


def staff_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_staff)(view_func)


@staff_required
def user_add(request):
    if request.method == "POST":
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User created: {user.email}")
            return redirect("user-add")
    else:
        form = AdminUserCreateForm()

    return render(request, "accounts/user_add.html", {"form": form})