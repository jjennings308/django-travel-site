# reviews/views.py
"""Reviews on catalogue pages. The list is an HTML fragment that the page loads after
it renders (``partials/_reviews.html``), so catalogue apps never import reviews."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ReportForm, ReviewForm
from .models import Review, ReviewReport
from .services import REPORTS_TO_HIDE, get_target, new_review, review_by, reviews_of, target_url, upsert_review

SHOWN = 10


def for_target(request, kind, slug):
    target = get_target(kind, slug)
    reviews = reviews_of(target)
    mine = review_by(request.user, target)
    reported = set()
    if request.user.is_authenticated:
        reported = set(ReviewReport.objects.filter(reporter=request.user, review__in=reviews).values_list("review_id", flat=True))
    return render(request, "reviews/_list.html", {
        "target": target, "kind": kind, "reviews": reviews[:SHOWN], "total": target.review_count,
        "mine": mine, "reported": reported, "report_form": ReportForm(), "back": target_url(target) + "#reviews",
        "rounded": int(round(target.average_rating or 0)),
    })


@login_required
def write(request, kind, slug):
    target = get_target(kind, slug)
    mine = review_by(request.user, target)
    form = ReviewForm(request.POST or None, instance=mine or new_review(request.user, target))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        upsert_review(request.user, target, data["rating"], data["comment"], data["title"], data["visit_date"])
        messages.success(request, "Thanks, your review is up." if mine is None else "Your review was updated.")
        return redirect(target_url(target) + "#reviews")
    return render(request, "reviews/review_form.html", {
        "form": form, "target": target, "kind": kind, "mine": mine, "back": target_url(target),
    })


@login_required
@require_POST
def delete(request, pk):
    review = get_object_or_404(Review, pk=pk, user=request.user)
    target = review.target
    review.delete()
    messages.success(request, "Your review was deleted.")
    return redirect(target_url(target) + "#reviews" if target else "pages:dashboard")


@login_required
@require_POST
def report(request, pk):
    review = get_object_or_404(Review, pk=pk, is_approved=True)
    back = target_url(review.target) + "#reviews" if review.target else reverse("pages:dashboard")
    form = ReportForm(request.POST)
    if review.user_id == request.user.pk or not form.is_valid():
        messages.error(request, "That report couldn't be sent.")
        return redirect(back)
    try:
        with transaction.atomic():
            ReviewReport.objects.create(review=review, reporter=request.user, **form.cleaned_data)
    except IntegrityError:
        messages.info(request, "You've already reported that review.")
        return redirect(back)
    open_reports = review.reports.filter(is_resolved=False).count()
    fields = {"report_count": review.reports.count(), "is_flagged": True}
    if open_reports >= REPORTS_TO_HIDE:
        fields["is_approved"] = False
    for name, value in fields.items():
        setattr(review, name, value)
    review.save(update_fields=list(fields))

    from apps.notifications.services import notify_staff
    hidden = " It has been hidden until someone looks at it." if not review.is_approved else ""
    notify_staff("review_reported", f"Review reported: {review.get_review_target_name()}",
                 f"@{request.user.username} reported {review.author_name}'s review of "
                 f"{review.get_review_target_name()} ({review.get_review_type_display()}): "
                 f"{form.instance.get_reason_display()}.{hidden}",
                 reverse("admin:reviews_reviewreport_changelist") + "?is_resolved__exact=0", obj=review,
                 exclude=request.user)
    messages.success(request, "Thanks, our team will take a look.")
    return redirect(back)
