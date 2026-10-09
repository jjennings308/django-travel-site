# admin_tools/views.py
"""Staff CSV import (upload -> preview -> confirm) and export of activities, events and locations."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.utils.breadcrumbs import build_breadcrumbs

from .importers import IMPORT_ORDER, KINDS as SPECS, MAX_ROWS, Importer, export_csv, template_csv

SESSION_KEY = "csv_import"
MAX_BYTES = 5 * 1024 * 1024
KINDS = {kind: SPECS[kind].label for kind in IMPORT_ORDER}


def staff_only(view):
    """Signed in and ``User.can_access_staff``; 403 otherwise."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.can_access_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _crumbs(*tail):
    return build_breadcrumbs([("Staff", "pages:staff_dashboard"), ("Import", "admin_tools:import" if tail else None), *tail])


@staff_only
def import_start(request):
    """Choose activities or events and upload a CSV."""
    if request.method == "POST":
        kind = request.POST.get("kind")
        upload = request.FILES.get("file")
        if kind not in KINDS or upload is None:
            messages.error(request, "Choose what you're importing and a CSV file.")
        elif upload.size > MAX_BYTES:
            messages.error(request, "That file is over 5 MB. Split it into smaller files.")
        else:
            raw = upload.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")  # Excel's default on Windows
            request.session[SESSION_KEY] = {"kind": kind, "text": text, "name": upload.name}
            return redirect("admin_tools:import_preview")
    help_columns = {kind: [(c, c in SPECS[kind].required, SPECS[kind].example.get(c, "")) for c in SPECS[kind].columns] for kind in KINDS}
    return render(request, "admin_tools/import_start.html", {
        "kinds": KINDS, "help_columns": help_columns, "max_rows": MAX_ROWS,
        "breadcrumb_list": _crumbs(),
    })


@staff_only
def import_preview(request):
    """Show what each row will do; POST imports the valid rows."""
    pending = request.session.get(SESSION_KEY)
    if not pending:
        return redirect("admin_tools:import")
    importer = Importer(pending["kind"], pending["text"]).parse()
    if request.method == "POST":
        done = importer.apply(request.user)
        del request.session[SESSION_KEY]
        created = sum(r.action == "create" for r, _ in done)
        updated = len(done) - created
        skipped = importer.counts["error"]
        messages.success(request, f"Imported {KINDS[pending['kind']].lower()}: {created} created, {updated} updated"
                                  + (f", {skipped} row(s) with errors skipped." if skipped else "."))
        url_name = SPECS[pending["kind"]].url_name
        return render(request, "admin_tools/import_done.html", {
            "kind_label": KINDS[pending["kind"]],
            "done": [(row, obj, reverse(url_name, args=[obj.slug])) for row, obj in done],
            "breadcrumb_list": _crumbs(("Done", None)),
        })
    return render(request, "admin_tools/import_preview.html", {
        "importer": importer, "counts": importer.counts, "kind_label": KINDS[pending["kind"]],
        "file_name": pending["name"], "breadcrumb_list": _crumbs(("Preview", None)),
    })


@staff_only
@require_POST
def import_cancel(request):
    request.session.pop(SESSION_KEY, None)
    return redirect("admin_tools:import")


@staff_only
def import_template(request, kind):
    if kind not in KINDS:
        raise PermissionDenied
    response = HttpResponse(template_csv(kind), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{kind}-import-template.csv"'
    return response


@staff_only
def export(request, kind):
    """Download the published items of one kind, in the import columns."""
    if kind not in KINDS:
        raise PermissionDenied
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{kind}-export-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("\ufeff")  # BOM, so Excel reads accents (café, München) correctly
    export_csv(kind, response)
    return response
