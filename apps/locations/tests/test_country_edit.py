from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.locations.models import Country

User = get_user_model()


class CountryEditTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        self.country = Country.objects.create(
            name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe",
            description="Old text.", visa_required=True,
        )
        self.url = reverse("locations:country_edit", args=["testland"])

    def test_form_is_prefilled(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, 'value="Testland"')
        self.assertContains(response, "Old text.")
        self.assertContains(response, '<option value="Europe" selected>')
        self.assertContains(response, "checked")

    def test_saving_updates_the_country(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, {
            "name": "Testland", "iso_code": "tl", "iso3_code": "tld", "continent": "Asia",
            "description": "New text.", "latitude": "", "longitude": "",
        })
        self.assertRedirects(response, reverse("locations:country_detail", args=["testland"]))
        self.country.refresh_from_db()
        self.assertEqual((self.country.continent, self.country.description, self.country.visa_required), ("Asia", "New text.", False))

    def test_other_users_are_turned_away(self):
        other = User.objects.create_user("other", "other@example.com", "pw-1234-abcd")
        self.client.force_login(other)
        self.assertRedirects(self.client.get(self.url), reverse("locations:country_detail", args=["testland"]))
