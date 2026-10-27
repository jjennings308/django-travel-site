"""Finding a city by typing, and adding one that isn't listed (docs/plans/day-first-planning.md, P1)."""
from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country, Region
from apps.locations.widgets import CitySearchInput, CitySearchMultiple

User = get_user_model()
APPROVED, PENDING = ApprovalStatus.APPROVED, ApprovalStatus.PENDING


class Fixture(TestCase):
    def setUp(self):
        self.member = User.objects.create_user("mem", "mem@example.com", "pw-1234-abcd")
        self.other = User.objects.create_user("oth", "oth@example.com", "pw-1234-abcd")
        self.at = Country.objects.create(name="Austria", slug="at", iso_code="AT", iso3_code="AUT", continent="Europe",
                                         latitude=47.5, longitude=14.5, approval_status=APPROVED)
        self.de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                         approval_status=APPROVED)
        self.upper = Region.objects.create(name="Upper Austria", code="OOE", country=self.at, approval_status=APPROVED)

        def city(name, country, status=APPROVED, by=None, **extra):
            return City.objects.create(name=name, slug=name.lower().replace(" ", "-"), country=country, latitude=0,
                                       longitude=0, approval_status=status, submitted_by=by, **extra)

        self.city = city
        self.munich = city("München", self.de, timezone="Europe/Berlin")
        self.munster = city("Münster", self.de)
        self.salzburg = city("Salzburg", self.at)
        self.mine = city("Hallstatt", self.at, status=PENDING, by=self.member)
        self.theirs = city("Halls Secret", self.at, status=PENDING, by=self.other)

    def names(self, q, user=None, **extra):
        if user:
            self.client.force_login(user)
        data = self.client.get(reverse("locations:city_search"), {"q": q, **extra}).json()
        return [row["name"] for row in data["results"]]


class SearchTests(Fixture):
    def test_accents_dont_matter_and_an_exact_name_comes_first(self):
        self.assertEqual(self.names("munchen"), ["München"])
        self.assertEqual(self.names("Mün")[:2], ["München", "Münster"])
        self.assertEqual(self.names("salzbrug"), ["Salzburg"])  # a typo still finds it

    def test_the_results_carry_what_the_box_needs(self):
        row = self.client.get(reverse("locations:city_search"), {"q": "munchen"}).json()["results"][0]
        self.assertEqual({k: row[k] for k in ("id", "name", "country", "timezone", "flag", "pending")},
                         {"id": self.munich.pk, "name": "München", "country": "Germany", "timezone": "Europe/Berlin",
                          "flag": "🇩🇪", "pending": False})
        self.assertEqual(set(row), {"id", "name", "label", "region", "country", "flag", "timezone", "lat", "lng",
                                    "pending"})

    def test_pending_cities_only_for_their_submitter(self):
        self.assertEqual(self.names("halls"), [])  # visitors: approved only
        self.assertEqual(self.names("halls", self.member), ["Hallstatt"])
        self.assertEqual(self.names("halls", self.other), ["Halls Secret"])

    def test_a_country_narrows_it_and_at_most_ten(self):
        self.assertEqual(self.names("s", country="AT"), ["Salzburg"])
        self.assertEqual(self.names("mun", country=str(self.at.pk)), [])
        for n in range(12):
            self.city(f"Springfield {n}", self.de)
        self.assertEqual(len(self.names("springfield")), 10)
        self.assertEqual(self.names(""), [])


class NewCityTests(Fixture):
    def post(self, user=None, **data):
        self.client.force_login(user or self.member)
        return self.client.post(reverse("locations:city_new"), data, HTTP_X_REQUESTED_WITH="fetch")

    def test_a_new_city_is_pending_and_usable_by_its_submitter(self):
        staff = User.objects.create_superuser("st", "st@example.com", "pw-1234-abcd")
        response = self.post(name="  Gosau ", country=self.at.pk, region=self.upper.pk)
        city = City.objects.get(name="Gosau")
        self.assertEqual(response.json()["city"]["id"], city.pk)
        self.assertEqual((city.approval_status, city.submitted_by, city.region), (PENDING, self.member, self.upper))
        self.assertEqual((float(city.latitude), float(city.longitude)), (47.5, 14.5))  # the country's centre
        self.assertTrue(staff.notifications.exists())  # in the approval queue, as any submission
        self.assertEqual(self.names("gosau", self.member), ["Gosau"])

    def test_one_already_visible_is_returned_not_duplicated(self):
        self.assertEqual(self.post(name="salzburg", country=self.at.pk).json()["city"]["id"], self.salzburg.pk)
        self.assertEqual(self.post(name="Hallstatt", country=self.at.pk).json()["city"]["id"], self.mine.pk)
        response = self.post(user=self.other, name="Hallstatt", country=self.at.pk)  # someone else's pending one
        self.assertEqual(response.status_code, 400)
        self.assertEqual(City.objects.filter(name="Hallstatt").count(), 1)

    def test_errors_and_the_no_javascript_page(self):
        self.assertEqual(self.post(name="Gosau", country=self.de.pk, region=self.upper.pk).status_code, 400)
        self.client.force_login(self.member)
        page = self.client.get(reverse("locations:city_new"), {"name": "Gosau", "next": "/trips/"})
        self.assertContains(page, 'value="Gosau"')
        response = self.client.post(reverse("locations:city_new"), {"name": "Gosau", "country": self.at.pk,
                                                                     "next": "/trips/"})
        self.assertRedirects(response, "/trips/", fetch_redirect_response=False)
        response = self.client.post(reverse("locations:city_new"), {"name": "Bad Ischl", "country": self.at.pk,
                                                                     "next": "https://evil.example/"})
        self.assertEqual(response["Location"], reverse("locations:city_detail", args=["bad-ischl-at"]))

    def test_signed_out_visitors_cant_add(self):
        response = self.client.post(reverse("locations:city_new"), {"name": "Gosau", "country": self.at.pk})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(City.objects.filter(name="Gosau").exists())


class WidgetTests(Fixture):
    def form(self, widget, value=None):
        choices = [("", "---------"), ("This trip", [(self.munich.pk, "München, DE")]),
                   ("Everywhere else", [(self.salzburg.pk, "Salzburg, AT")])]

        class F(forms.Form):
            city = forms.ChoiceField(choices=choices, required=False, widget=widget)

        return F(initial={"city": value})

    def test_the_box_has_chips_and_a_no_javascript_select(self):
        html = str(self.form(CitySearchInput(zones={str(self.munich.pk): "Europe/Berlin"}), self.salzburg.pk)["city"])
        self.assertIn('x-data="citySearch(\'id_city_config\')"', html)
        self.assertIn("x-cloak", html)  # hidden without JavaScript
        self.assertIn('x-bind:name="multiple ? null : name"', html)  # the hidden input is named only by Alpine
        self.assertIn('"chips": [{"id": "%d", "label": "M\\u00fcnchen, DE", "timezone": "Europe/Berlin"}]' % self.munich.pk,
                      html)
        self.assertIn('"selected": [{"id": "%d"' % self.salzburg.pk, html)
        fallback = html[html.index("<noscript>"):html.index("</noscript>")]
        self.assertIn('<select name="city" id="id_city_fallback"', fallback)
        self.assertIn('<optgroup label="This trip">', fallback)
        self.assertIn(f'value="{self.munich.pk}" data-tz="Europe/Berlin"', fallback)
        self.assertIn(f'value="{self.salzburg.pk}" selected', fallback)

    def test_several_cities(self):
        class F(forms.Form):
            cities = forms.MultipleChoiceField(choices=[(self.munich.pk, "München"), (self.salzburg.pk, "Salzburg")],
                                               widget=CitySearchMultiple())

        form = F({"cities": [str(self.munich.pk), str(self.salzburg.pk)]})
        self.assertTrue(form.is_valid())
        self.assertEqual(len(form.cleaned_data["cities"]), 2)
        html = str(form["cities"])
        self.assertIn('"multiple": true', html)
        self.assertIn("multiple", html[html.index("<noscript>"):])
