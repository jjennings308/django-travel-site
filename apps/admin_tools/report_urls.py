"""Member-facing reporting (site roadmap R15), mounted at /report/ (namespace ``reports``)."""
from django.urls import path

from . import reports

urlpatterns = [
    path("<str:kind>/<int:pk>/", reports.report, name="report"),
]
