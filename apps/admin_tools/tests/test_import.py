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
from apps.locations.models import POI, City, Country, Region

User = get_user_model()


def upload(text, name="data.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ImportFixture(TestCase):
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


class ImportTests(ImportFixture):
    """Activities and events."""

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


class LocationImportTests(ImportFixture):
    """Countries, regions, cities and places, plus export and round trip."""

    def test_location_chain(self):
        steps = [
            ("country", "name,iso_code,iso3_code,continent,visa_required\nIceland,IS,ISL,Europe,no\n"),
            ("region", "name,country,code\nCapital Region,Iceland,1\n"),
            ("city", "name,country,region,latitude,longitude,capital\nReykjavik,Iceland,Capital Region,64.1466,-21.9426,country\n"),
            ("poi", "name,city,country,type,latitude,longitude,wheelchair_accessible\nHallgrimskirkja,Reykjavik,Iceland,temple,64.1417,-21.9266,yes\n"),
        ]
        for kind, text in steps:
            with self.subTest(kind=kind):
                page = self.preview(kind, text)
                self.assertEqual(page.context["counts"], {"create": 1, "update": 0, "error": 0},
                                 [r.errors for r in page.context["importer"].rows])
                self.confirm()
        iceland = Country.objects.get(iso_code="IS")
        city = City.objects.get(name="Reykjavik")
        self.assertEqual((iceland.visa_required, iceland.approval_status, iceland.flag_emoji), (False, ApprovalStatus.APPROVED, "🇮🇸"))
        self.assertEqual((city.region.name, city.capital_type, city.is_capital), ("Capital Region", "country", True))
        poi = city.pois.get() if hasattr(city, "pois") else POI.objects.get(city=city)
        self.assertEqual((poi.poi_type, poi.wheelchair_accessible, poi.approval_status), ("temple", True, ApprovalStatus.APPROVED))
        # matched by ISO code: renaming via the file updates, not duplicates
        self.preview("country", "name,iso_code,iso3_code,continent\nIceland,is,ISL,Europe\n")
        self.assertEqual(self.client.get(reverse("admin_tools:import_preview")).context["counts"]["update"], 1)

    def test_place_needs_an_existing_city_and_region_in_country(self):
        page = self.preview("poi", "name,city,latitude,longitude\nSomewhere,Atlantis,1,2\n")
        self.assertContains(page, "isn&#x27;t a city in the catalogue")
        france = Country.objects.create(name="France", slug="france", iso_code="FR", iso3_code="FRA", continent="Europe")
        page = self.preview("city", "name,country,region,latitude,longitude\nLyon,France,Bavaria,45.76,4.83\n")
        self.assertContains(page, "isn&#x27;t a region in the catalogue")
        self.assertTrue(france)

    def test_export_round_trip(self):
        Activity.objects.create(category=self.festival, name="Oktoberfest", description="Beer, music", city=self.munich,
                                recurrence="yearly", usual_months=[9, 10], created_by=self.staff, visibility="public",
                                approval_status=ApprovalStatus.APPROVED)
        Activity.objects.create(category=self.festival, name="Secret", description="d", created_by=self.staff,
                                visibility="private")
        for kind in ("country", "region", "city", "activity"):
            with self.subTest(kind=kind):
                response = self.client.get(reverse("admin_tools:export", args=[kind]))
                self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
                text = response.content.decode("utf-8-sig")
                if kind == "activity":
                    self.assertIn('"Beer, music"', text)  # comma inside a cell is quoted
                    self.assertIn("Sep;Oct", text)
                    self.assertNotIn("Secret", text)  # only published items
                page = self.preview(kind, text)
                counts = page.context["counts"]
                self.assertEqual((counts["create"], counts["error"]), (0, 0))
                self.assertEqual([r.changes for r in page.context["importer"].rows], [[]] * counts["update"])
