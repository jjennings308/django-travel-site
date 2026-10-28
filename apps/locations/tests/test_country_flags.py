"""A flag picture for every country (docs/plans/country-flags.md, C1)."""
import re
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.approval_system.models import ApprovalStatus
from apps.locations import flags
from apps.locations.models import Country
from apps.media_app.models import Media

User = get_user_model()
IMPORT_COUNTRIES = Path(__file__).resolve().parents[1] / "management" / "commands" / "import_countries.py"



class PngTests(SimpleTestCase):
    def test_every_committed_png_is_1200_by_900(self):
        pngs = sorted(flags.FLAGS.glob("*.png"))
        self.assertGreater(len(pngs), 240)
        for png in pngs:
            with Image.open(png) as image:
                self.assertEqual(image.size, (1200, 900), png.name)
        self.assertTrue((flags.FLAGS / "LICENSE").exists())

    def test_every_seeded_country_has_one(self):
        codes = re.findall(r'\("[^"]+", "([A-Z]{2})", "[A-Z]{3}"', IMPORT_COUNTRIES.read_text())
        self.assertGreater(len(codes), 100)
        missing = [code for code in codes if not (flags.FLAGS / f"{code.lower()}.png").exists()]
        self.assertEqual(missing, [])  # flag-icons has every sovereign country import_countries seeds


class Fixture(TestCase):
    """Each class gets its own uploads folder: the parallel runner sends classes to different processes, and
    the flag files have fixed names, so a shared folder let one class rewrite (or delete) another's."""

    @classmethod
    def setUpClass(cls):
        cls.media_root = tempfile.mkdtemp(prefix="sbl-test-flags-")
        cls._media_settings = override_settings(MEDIA_ROOT=cls.media_root, COUNTRY_FLAGS_ENABLED=True)
        cls._media_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_settings.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)

    def setUp(self):
        self.germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.france = Country.objects.create(name="France", slug="france", iso_code="FR", iso3_code="FRA",
                                             continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.kosovo = Country.objects.create(name="Nowhere", slug="nowhere", iso_code="QQ", iso3_code="QQQ",
                                             continent="Europe", approval_status=ApprovalStatus.APPROVED)

    def photo(self, country):
        media = Media(title="Eiffel Tower", uploaded_by=User.objects.create_user("p", "p@example.com", "x"))
        media.file.save("eiffel.jpg", ContentFile(b"\xff\xd8\xff photo"), save=False)
        media.save()
        country.featured_media = media
        country.save(update_fields=["featured_media"])
        return media

    def run_command(self, *args):
        out = StringIO()
        call_command("country_flags", *args, stdout=out)
        return out.getvalue()


class CommandTests(Fixture):
    def test_one_media_per_country_reused_on_a_second_run(self):
        photo = self.photo(self.france)
        dry = self.run_command("--dry-run")
        self.assertIn("Would make 1 flag picture", dry)
        self.assertIn("FR  France  (photo: Eiffel Tower)", dry)
        self.assertIn("No flag PNG for 1: QQ", dry)
        self.assertFalse(Media.objects.filter(title__startswith="Flag of").exists())
        out = self.run_command()
        self.assertIn("Made 1 flag picture; already set: 0.", out)
        self.assertIn("Replaced a photo with the flag for 1", out)
        self.assertIn("FR  France  (photo: Eiffel Tower)", out)  # the photo's name, not the flag's
        for country in (self.germany, self.france):
            country.refresh_from_db()
            self.assertEqual(country.featured_media_id, country.flag_media_id)
            self.assertEqual(country.flag_media.title, f"Flag of {country.name}")
            self.assertTrue(country.flag_media.is_flag)
            self.assertEqual((country.flag_media.uploaded_by, country.flag_media.is_user_generated), (None, False))
        self.assertTrue(Media.objects.filter(pk=photo.pk).exists())  # the photo is kept
        self.assertFalse(photo.is_flag)
        self.assertEqual(Media.objects.filter(title__startswith="Flag of").count(), 2)
        self.assertIn("Made 0 flag pictures; already set: 2.", self.run_command())
        self.assertEqual(Media.objects.filter(title__startswith="Flag of").count(), 2)

    def test_one_country(self):
        self.run_command("--country", "de")
        self.germany.refresh_from_db()
        self.france.refresh_from_db()
        self.assertIsNotNone(self.germany.flag_media_id)
        self.assertIsNone(self.france.flag_media_id)

    def test_a_missing_file_is_made_again(self):
        flags.attach(self.germany)
        self.germany.refresh_from_db()
        old = self.germany.flag_media
        old.file.storage.delete(old.file.name)
        self.run_command("--country", "DE")
        self.germany.refresh_from_db()
        self.assertNotEqual(self.germany.flag_media_id, old.pk)


class NewCountryTests(Fixture):
    def test_the_add_page(self):
        user = User.objects.create_user("m", "m@example.com", "pw-1234-abcd")
        self.client.force_login(user)
        self.client.post(reverse("locations:country_add"), {"name": "Iceland", "iso_code": "is", "iso3_code": "isl",
                                                            "continent": "Europe"})
        iceland = Country.objects.get(iso_code="IS")
        self.assertEqual((iceland.featured_media_id, iceland.flag_media.title),
                         (iceland.flag_media_id, "Flag of Iceland"))

    def test_the_csv_import(self):
        staff = User.objects.create_user("staffer", "s@example.com", "pw-1234-abcd")
        staff.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard",
                                                          content_type__app_label="accounts"))
        self.client.force_login(staff)
        from django.core.files.uploadedfile import SimpleUploadedFile
        csv = "name,iso_code,iso3_code,continent,visa_required\nIceland,IS,ISL,Europe,no\nGermany,DE,DEU,Europe,no\n"
        self.client.post(reverse("admin_tools:import"), {
            "kind": "country", "file": SimpleUploadedFile("c.csv", csv.encode(), content_type="text/csv")})
        self.client.post(reverse("admin_tools:import_preview"))
        iceland = Country.objects.get(iso_code="IS")
        self.assertEqual(iceland.featured_media_id, iceland.flag_media_id)
        self.assertIsNotNone(iceland.flag_media_id)
        self.germany.refresh_from_db()
        self.assertIsNone(self.germany.flag_media_id)  # an update isn't a new country

    def test_import_countries(self):
        User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        call_command("import_countries", stdout=StringIO())
        canada = Country.objects.get(iso_code="CA")
        self.assertEqual((canada.featured_media_id, canada.flag_media.title), (canada.flag_media_id, "Flag of Canada"))

    @override_settings(COUNTRY_FLAGS_ENABLED=False)
    def test_off_makes_nothing(self):
        self.assertEqual(flags.attach(self.germany), (None, "off"))


class PageTests(Fixture):
    def test_a_flag_is_contained_a_photo_covers(self):
        flags.attach(self.germany)
        self.photo(self.france)
        flags.attach(self.france)  # keeps the photo as the picture; the flag is only flag_media
        page = self.client.get(reverse("locations:country_detail", args=["germany"])).content.decode()
        self.assertIn('data-country-picture="flag"', page)
        self.assertIn("object-contain", page.split('data-country-picture="flag"')[0].rsplit("<img", 1)[1])
        page = self.client.get(reverse("locations:country_detail", args=["france"])).content.decode()
        self.assertIn('data-country-picture="photo"', page)
        listing = self.client.get(reverse("locations:country_list")).content.decode()
        self.assertIn('alt="Flag of Germany" class="h-full w-full rounded-t-xl bg-warm-100 object-contain', listing)
        self.assertIn('alt="France" class="h-full w-full rounded-t-xl object-cover', listing)

    def test_the_share_picture_is_the_flag(self):
        flags.attach(self.germany)
        page = self.client.get(reverse("locations:country_detail", args=["germany"])).content.decode()
        self.germany.refresh_from_db()
        self.assertIn(f'<meta property="og:image" content="http://127.0.0.1:8000{self.germany.flag_media.file.url}">',
                      page)


class UseTheFlagTests(Fixture):
    def test_choosing_a_photo_then_using_the_flag_again(self):
        staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        flags.attach(self.france)
        self.france.refresh_from_db()
        flag = self.france.flag_media
        photo = self.photo(self.france)
        self.client.force_login(staff)
        url = reverse("locations:country_edit", args=["france"])
        self.assertContains(self.client.get(url), "data-use-flag")
        data = {"name": "France", "iso_code": "FR", "iso3_code": "FRA", "continent": "Europe", "latitude": "",
                "longitude": ""}
        self.client.post(url, {**data, "featured_media_id": photo.pk})
        self.france.refresh_from_db()
        self.assertEqual((self.france.featured_media, self.france.flag_media), (photo, flag))
        self.client.post(url, {**data, "use_flag": "1"})
        self.france.refresh_from_db()
        self.assertEqual(self.france.featured_media, flag)
        self.assertNotContains(self.client.get(url), "data-use-flag")
