"""Staff CSV import of activities and events: preview, create, update, errors."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country, Region

User = get_user_model()


def upload(text, name="data.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ImportTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd")
        self.staff.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard",
                                                               content_type__app_label="accounts"))
        self.germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.bavaria = Region.objects.create(country=self.germany, name="Bavaria", slug="bavaria")
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.germany, region=self.bavaria,
                                          latitude=48, longitude=11, approval_status=ApprovalStatus.APPROVED)
        self.festival = ActivityCategory.objects.get(name="Festival")
        self.client.force_login(self.staff)

    def preview(self, kind, text):
        self.client.post(reverse("admin_tools:import"), {"kind": kind, "file": upload(text)})
        return self.client.get(reverse("admin_tools:import_preview"))

    def confirm(self):
        return self.client.post(reverse("admin_tools:import_preview"))

    def test_staff_only(self):
        member = User.objects.create_user("m", "m@example.com", "pw-1234-abcd")
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("admin_tools:import")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("admin_tools:import")).status_code, 302)

    def test_templates_download(self):
        for kind in ("activity", "event"):
            response = self.client.get(reverse("admin_tools:import_template", args=[kind]))
            self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
            self.assertIn(b"Oktoberfest", response.content)

    def test_template_imports_cleanly(self):
        """The downloadable examples are valid: activity first, then the event that refers to it."""
        self.preview("activity", self.client.get(reverse("admin_tools:import_template", args=["activity"])).content.decode())
        self.confirm()
        page = self.preview("event", self.client.get(reverse("admin_tools:import_template", args=["event"])).content.decode())
        self.assertEqual(page.context["counts"], {"create": 1, "update": 0, "error": 0})

    def test_activity_create_then_update(self):
        csv = ("Name,Category,Description,City,Country,Recurrence,Usual Months,Booking required\n"
               "Oktoberfest,festival,Beer.,Munich,Germany,Every year,\"Sep, Oct\",yes\n")
        page = self.preview("activity", csv)
        self.assertEqual(page.context["counts"], {"create": 1, "update": 0, "error": 0})
        self.assertFalse(Activity.objects.exists())  # preview saves nothing
        self.confirm()
        okto = Activity.objects.get()
        self.assertEqual((okto.city, okto.region, okto.country), (self.munich, self.bavaria, self.germany))
        self.assertEqual((okto.recurrence, okto.usual_months, okto.booking_required), ("yearly", [9, 10], True))
        self.assertEqual((okto.approval_status, okto.visibility, okto.source, okto.created_by),
                         (ApprovalStatus.APPROVED, "public", "import", self.staff))

        page = self.preview("activity", "name,category,description,timing_notes\nOKTOBERFEST,Festival,Beer and brass.,\n")
        self.assertEqual(page.context["counts"], {"create": 0, "update": 1, "error": 0})
        self.assertEqual(page.context["importer"].rows[0].changes, ["Description"])  # not Name: capitals ignored
        self.confirm()
        okto.refresh_from_db()
        self.assertEqual(Activity.objects.count(), 1)
        self.assertEqual((okto.name, okto.description, okto.city, okto.recurrence),
                         ("Oktoberfest", "Beer and brass.", self.munich, "yearly"))  # matched ignoring capitals; name kept

    def test_event_rows(self):
        okto = Activity.objects.create(category=self.festival, name="Oktoberfest", description="d", created_by=self.staff,
                                       visibility="public", approval_status=ApprovalStatus.APPROVED)
        csv = ("name,start_date,end_date,start_time,activity,category,description,city,country,free\n"
               "Oktoberfest 2027,2027-09-18,10/03/2027,10:00 AM,Oktoberfest,,Beer.,Munich,Germany,yes\n"
               "Village Fair,2027-07-01,,,,Community,Fun.,Smallville,Germany,no\n"
               "No Category Gig,2027-07-02,,,,,Loud.,Munich,Germany,no\n")
        page = self.preview("event", csv)
        self.assertEqual(page.context["counts"], {"create": 2, "update": 0, "error": 1})
        self.assertContains(page, "Choose a category (or the activity this is a date for)")
        self.confirm()
        event = Event.objects.get(name="Oktoberfest 2027")
        self.assertEqual((event.related_activity, event.category, event.city), (okto, self.festival, self.munich))
        self.assertEqual((event.end_date, event.start_time, event.is_free), (date(2027, 10, 3), time(10, 0), True))
        fair = Event.objects.get(name="Village Fair")  # unlisted town kept as typed, for staff to link
        self.assertEqual((fair.city, fair.country, fair.location_text), (None, self.germany, "Smallville"))
        self.assertEqual(fair.approval_status, ApprovalStatus.APPROVED)

    def test_errors_are_reported_and_skipped(self):
        csv = ("name,category,description,city\n"
               "Good one,Festival,Fine.,Munich\n"
               "Bad category,Knitting,x,\n"
               "Good one,Festival,Same again.,\n"
               ",Festival,No name,\n")
        page = self.preview("activity", csv)
        self.assertEqual(page.context["counts"], {"create": 1, "update": 0, "error": 3})
        self.assertContains(page, "isn&#x27;t a category")
        self.assertContains(page, "same item as row 2")
        self.confirm()
        self.assertEqual(list(Activity.objects.values_list("name", flat=True)), ["Good one"])

    def test_bad_dates_and_missing_columns(self):
        page = self.preview("event", "name,start_date,description,city\nGig,next tuesday,Loud.,Munich\n")
        self.assertContains(page, "isn&#x27;t a date")
        page = self.preview("event", "name,description\nGig,Loud.\n")
        self.assertContains(page, "Missing required column(s): start_date")
