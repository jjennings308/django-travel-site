from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.activities.models import ActivityCategory
from apps.events.models import Event
from apps.locations.models import City, Country, Region

User = get_user_model()
TODAY = date.today()


class EventFixture(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd", is_staff=True)
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2,
                                        approval_status=ApprovalStatus.APPROVED)
        self.music = ActivityCategory.objects.get(name="Music")  # shared list, seeded by activities 0008

    def make(self, name, status=ApprovalStatus.APPROVED, start=None, **kw):
        return Event.objects.create(name=name, category=self.music, description="d", city=self.city,
                                    start_date=start or TODAY + timedelta(days=10),
                                    approval_status=status, **kw)

    def payload(self, **over):
        data = {"name": "Jazz Night", "category": self.music.pk, "description": "Live jazz.",
                "city": self.city.pk, "start_date": (TODAY + timedelta(days=5)).isoformat(),
                "event_type": "public", "is_free": "on"}
        data.update(over)
        return data


class ListAndVisibilityTests(EventFixture):
    def test_list_shows_only_approved_upcoming(self):
        self.make("Approved Gig")
        self.make("Pending Gig", status=ApprovalStatus.PENDING)
        self.make("Old Gig", start=TODAY - timedelta(days=30))
        response = self.client.get(reverse("events:event_list"))
        self.assertContains(response, "Approved Gig")
        self.assertNotContains(response, "Pending Gig")
        self.assertNotContains(response, "Old Gig")
        self.assertContains(self.client.get(reverse("events:event_list") + "?when=past"), "Old Gig")

    def test_filters(self):
        self.make("Free Gig", is_free=True)
        self.make("Paid Gig", is_free=False)
        response = self.client.get(reverse("events:event_list") + "?free=1&q=gig")
        self.assertContains(response, "Free Gig")
        self.assertNotContains(response, "Paid Gig")

    def test_unapproved_event_is_404_except_for_creator_and_staff(self):
        event = self.make("Secret", status=ApprovalStatus.PENDING, created_by=self.alice)
        url = reverse("events:event_detail", args=[event.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Only you and our team can see this until")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)


class SubmitAndEditTests(EventFixture):
    def test_user_submission_goes_to_review(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:event_add"), self.payload())
        event = Event.objects.get(name="Jazz Night")
        self.assertRedirects(response, reverse("events:event_detail", args=[event.slug]))
        self.assertEqual((event.approval_status, event.created_by, event.submitted_by), (ApprovalStatus.PENDING, self.alice, self.alice))
        self.assertContains(self.client.get(reverse("events:my_events")), "Jazz Night")
        self.assertNotContains(self.client.get(reverse("events:event_list")), "Jazz Night")

    def test_staff_submission_is_published(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), self.payload())
        self.assertEqual(Event.objects.get(name="Jazz Night").approval_status, ApprovalStatus.APPROVED)

    def test_approval_publishes_it(self):
        event = self.make("Queued", status=ApprovalStatus.PENDING, created_by=self.alice)
        event.approve(self.staff)
        self.assertContains(self.client.get(reverse("events:event_list")), "Queued")

    def test_creator_can_edit_until_approved(self):
        event = self.make("Mine", status=ApprovalStatus.PENDING, created_by=self.alice)
        self.client.force_login(self.alice)
        edit = reverse("events:event_edit", args=[event.slug])
        self.assertEqual(self.client.get(edit).status_code, 200)
        Event.objects.filter(pk=event.pk).update(approval_status=ApprovalStatus.APPROVED)
        self.assertRedirects(self.client.get(edit), reverse("events:event_detail", args=[event.slug]))

    def test_editing_a_rejected_event_resubmits_it(self):
        event = self.make("Fix me", status=ApprovalStatus.REJECTED, created_by=self.alice)
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_edit", args=[event.slug]), self.payload(name="Fixed"))
        event.refresh_from_db()
        self.assertEqual((event.name, event.approval_status), ("Fixed", ApprovalStatus.PENDING))

    def test_others_cannot_edit_or_delete(self):
        event = self.make("Alice's", created_by=self.alice)
        self.client.force_login(self.bob)
        self.client.post(reverse("events:event_delete", args=[event.slug]))
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    def test_creator_can_delete_pending(self):
        event = self.make("Oops", status=ApprovalStatus.PENDING, created_by=self.alice)
        self.client.force_login(self.alice)
        self.assertRedirects(self.client.post(reverse("events:event_delete", args=[event.slug])), reverse("events:my_events"))
        self.assertFalse(Event.objects.filter(pk=event.pk).exists())

    def test_end_before_start_is_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:event_add"), self.payload(
            end_date=(TODAY + timedelta(days=1)).isoformat()))
        self.assertContains(response, "can&#x27;t be before the start date")
        self.assertFalse(Event.objects.exists())

    def test_add_requires_login(self):
        self.assertEqual(self.client.get(reverse("events:event_add")).status_code, 302)


class UnlistedCityTests(EventFixture):
    def setUp(self):
        super().setUp()
        self.austria = Country.objects.create(name="Austria", slug="austria", iso_code="AT", iso3_code="AUT",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)

    def submit_unlisted(self, **over):
        self.client.force_login(self.alice)
        data = self.payload(city="", country=self.austria.pk, location_text="Hallstatt")
        data.update(over)
        return self.client.post(reverse("events:event_add"), data)

    def test_user_can_submit_with_a_typed_city(self):
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.assertIsNone(event.city)
        self.assertEqual((event.place_name, event.needs_city_link), ("Hallstatt, Austria", True))
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), "Hallstatt, Austria")

    def test_city_or_country_and_town_is_required(self):
        response = self.submit_unlisted(country="", location_text="")
        self.assertContains(response, "Choose a city, or tick")
        response = self.submit_unlisted(location_text="")
        self.assertContains(response, "Choose a city, or tick")
        self.assertFalse(Event.objects.exists())

    def test_database_refuses_an_event_without_any_location(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.create(name="Nowhere", category=self.music, description="d", start_date=TODAY)

    def test_choosing_a_city_clears_typed_location(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_add"), self.payload(country=self.austria.pk, location_text="Hallstatt"))
        event = Event.objects.get(name="Jazz Night")
        self.assertEqual((event.city, event.country, event.location_text), (self.city, None, ""))

    def test_staff_link_to_existing_city(self):
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        graz = City.objects.create(name="Graz", slug="graz-at", country=self.austria, latitude=47, longitude=15,
                                   approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), "City not in the catalogue")
        self.client.post(reverse("events:event_link_city", args=[event.slug]), {"city": graz.pk})
        event.refresh_from_db()
        self.assertEqual((event.city, event.country, event.location_text), (graz, None, ""))

    def test_staff_create_city_and_link(self):
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_link_city", args=[event.slug]),
                         {"name": "Hallstatt", "latitude": "47.562", "longitude": "13.649"})
        event.refresh_from_db()
        self.assertEqual((event.city.name, event.city.country, event.city.approval_status),
                         ("Hallstatt", self.austria, ApprovalStatus.APPROVED))

    def test_new_city_gets_a_region_when_the_country_has_them(self):
        upper = Region.objects.create(country=self.austria, name="Upper Austria", slug="upper-austria")
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), "Upper Austria")
        url = reverse("events:event_link_city", args=[event.slug])
        self.client.post(url, {"name": "Hallstatt", "latitude": "47.562", "longitude": "13.649"})
        self.assertFalse(City.objects.filter(name="Hallstatt").exists())  # region required
        self.client.post(url, {"name": "Hallstatt", "latitude": "47.562", "longitude": "13.649", "region": upper.pk})
        event.refresh_from_db()
        self.assertEqual(event.city.region, upper)

    def test_existing_city_without_a_region_gets_one(self):
        upper = Region.objects.create(country=self.austria, name="Upper Austria", slug="upper-austria")
        bare = City.objects.create(name="Hallstatt", slug="hallstatt-at", country=self.austria, latitude=47, longitude=13,
                                   approval_status=ApprovalStatus.APPROVED)
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_link_city", args=[event.slug]),
                         {"name": "hallstatt", "latitude": "47.562", "longitude": "13.649", "region": upper.pk})
        bare.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual((event.city, bare.region), (bare, upper))

    def test_bad_coordinates_create_nothing(self):
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_link_city", args=[event.slug]), {"name": "Hallstatt", "latitude": "999", "longitude": "x"})
        self.assertFalse(City.objects.filter(name="Hallstatt").exists())

    def test_only_staff_can_link(self):
        self.submit_unlisted()
        event = Event.objects.get(name="Jazz Night")
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_link_city", args=[event.slug]), {"name": "X", "latitude": "1", "longitude": "1"})
        event.refresh_from_db()
        self.assertIsNone(event.city)

    def test_country_filter_includes_unlinked_events(self):
        self.submit_unlisted()
        Event.objects.filter(name="Jazz Night").update(approval_status=ApprovalStatus.APPROVED)
        response = self.client.get(reverse("events:event_list") + "?country=austria")
        self.assertContains(response, "Jazz Night")


class ActivityLinkTests(EventFixture):
    def setUp(self):
        super().setUp()
        from apps.activities.models import Activity
        self.festival = ActivityCategory.objects.get(name="Festival")
        self.okto = Activity.objects.create(category=self.festival, name="Oktoberfest", description="Beer and brass bands.",
                                            created_by=self.bob, visibility="public", approval_status=ApprovalStatus.APPROVED)

    def test_add_a_date_prefills_from_the_activity(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("events:event_add") + f"?activity={self.okto.pk}")
        self.assertContains(response, 'value="Oktoberfest"')
        self.assertContains(response, f'<option value="{self.okto.pk}" selected>')

    def test_add_a_date_prefills_the_activitys_city(self):
        self.okto.city = self.city
        self.okto.save()
        self.client.force_login(self.alice)
        response = self.client.get(reverse("events:event_add") + f"?activity={self.okto.pk}")
        self.assertContains(response, f'<option value="{self.city.pk}" selected>')

    def test_yearly_activity_event_offers_next_years_dates(self):
        self.okto.recurrence = "yearly"
        self.okto.save()
        this_year = Event.objects.create(
            name="Oktoberfest 2027", category=self.festival, related_activity=self.okto, description="Beer.",
            city=self.city, start_date=date(2027, 9, 18), end_date=date(2027, 10, 3),
            approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.alice)
        detail = reverse("events:event_detail", args=[this_year.slug])
        copy_url = reverse("events:event_add") + f"?copy={this_year.pk}"
        self.assertContains(self.client.get(detail), "Add 2028 dates")
        form = self.client.get(copy_url)
        for text in ('value="Oktoberfest 2028"', 'value="2028-09-18"', 'value="2028-10-03"', f'<option value="{self.okto.pk}" selected>'):
            self.assertContains(form, text)
        # once next year's exists, the button links to it instead
        Event.objects.create(name="Oktoberfest 2028", category=self.festival, related_activity=self.okto,
                             description="Beer.", city=self.city, start_date=date(2028, 9, 16),
                             approval_status=ApprovalStatus.APPROVED)
        page = self.client.get(detail)
        self.assertContains(page, "2028 dates")
        self.assertNotContains(page, "Add 2028 dates")

    def test_activity_page_lists_each_years_event(self):
        for year, status, by in ((2026, ApprovalStatus.APPROVED, self.bob), (2027, ApprovalStatus.APPROVED, self.bob),
                                 (2028, ApprovalStatus.PENDING, self.bob)):
            Event.objects.create(name=f"Oktoberfest {year}", category=self.festival, related_activity=self.okto,
                                 description="d", city=self.city, start_date=date(year, 9, 18),
                                 approval_status=status, created_by=by)
        self.client.force_login(self.alice)
        page = self.client.get(reverse("activities:activity_detail", args=[self.okto.slug]))
        self.assertContains(page, "Oktoberfest 2026")
        self.assertContains(page, "Oktoberfest 2027")
        self.assertNotContains(page, "Oktoberfest 2028")  # pending, someone else's

    def test_one_off_activity_has_no_next_year(self):
        event = Event.objects.create(name="Gig", category=self.festival, related_activity=self.okto, description="d",
                                     city=self.city, start_date=date(2027, 1, 1), approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse("events:event_detail", args=[event.slug])), "2028 dates")

    def test_event_inherits_category_from_activity(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("events:event_add"), self.payload(name="Oktoberfest 2027", category="", related_activity=self.okto.pk))
        event = Event.objects.get(name="Oktoberfest 2027")
        self.assertEqual((event.related_activity, event.category), (self.okto, self.festival))

    def test_category_or_activity_required(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("events:event_add"), self.payload(category=""))
        self.assertContains(response, "Choose a category")

    def test_dates_for_an_activity(self):
        self.make("Oktoberfest 2027", related_activity=self.okto)
        self.make("Unrelated Gig")
        response = self.client.get(reverse("events:event_list") + f"?activity={self.okto.slug}")
        self.assertContains(response, "Dates for")
        self.assertContains(response, "Oktoberfest 2027")
        self.assertNotContains(response, "Unrelated Gig")

    def test_activity_page_links_to_its_dates(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("activities:activity_detail", args=[self.okto.slug]))
        self.assertContains(response, reverse("events:event_list") + f"?activity={self.okto.slug}")
        self.assertContains(response, reverse("events:event_add") + f"?activity={self.okto.pk}")

    def test_event_page_names_its_activity(self):
        event = self.make("Oktoberfest 2027", related_activity=self.okto)
        self.assertContains(self.client.get(reverse("events:event_detail", args=[event.slug])), "This is a date for")


class SeasonalActivityTests(EventFixture):
    """Steelers-style activities: many dates a season, at one venue."""

    def setUp(self):
        super().setUp()
        from apps.activities.models import Activity
        from apps.locations.models import POI
        self.stadium = POI.objects.create(name="Testville Stadium", slug="testville-stadium", city=self.city, poi_type="sports",
                                          latitude=1, longitude=2, approval_status=ApprovalStatus.APPROVED)
        self.team = Activity.objects.create(category=self.music, name="See the Testers play", description="Home games.",
                                            venue=self.stadium, recurrence="seasonal", usual_months=[9, 10, 11, 12, 1],
                                            created_by=self.bob, visibility="public", approval_status=ApprovalStatus.APPROVED)
        self.game = Event.objects.create(name="Testers vs Rivals", category=self.music, description="d", city=self.city,
                                         poi=self.stadium, venue_name="Testville Stadium", related_activity=self.team,
                                         start_date=TODAY + timedelta(days=20), approval_status=ApprovalStatus.APPROVED)

    def test_add_a_date_prefills_the_venue(self):
        self.client.force_login(self.alice)
        page = self.client.get(reverse("events:event_add") + f"?activity={self.team.pk}")
        self.assertContains(page, f'<option value="{self.stadium.pk}" selected>')
        self.assertContains(page, 'value="Testville Stadium"')

    def test_venue_fills_city_and_name(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("events:event_add"), self.payload(name="Cup final", city="", poi=self.stadium.pk))
        final = Event.objects.get(name="Cup final")
        self.assertEqual((final.city, final.poi, final.venue_name), (self.city, self.stadium, "Testville Stadium"))
        self.assertContains(self.client.get(reverse("events:event_detail", args=[final.slug])),
                            reverse("locations:poi_detail", args=["testville-stadium"]))

    def test_add_another_date(self):
        self.client.force_login(self.alice)
        detail = self.client.get(reverse("events:event_detail", args=[self.game.slug]))
        self.assertContains(detail, "Add another date")
        self.assertNotContains(detail, f"Add {self.game.start_date.year + 1} dates")  # not the yearly button
        form = self.client.get(reverse("events:event_add") + f"?copy={self.game.pk}&another=1")
        self.assertContains(form, 'value="Testers vs Rivals"')
        self.assertContains(form, f'<option value="{self.stadium.pk}" selected>')
        self.assertIsNone(form.context["form"].initial["start_date"])

    def test_activity_page_groups_by_season_and_folds_past(self):
        from datetime import date
        Event.objects.create(name="Old game", category=self.music, description="d", city=self.city, related_activity=self.team,
                             start_date=date(2025, 10, 5), approval_status=ApprovalStatus.APPROVED)
        Event.objects.create(name="January game", category=self.music, description="d", city=self.city, related_activity=self.team,
                             start_date=date(TODAY.year + 2, 1, 4), approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.alice)
        page = self.client.get(reverse("activities:activity_detail", args=[self.team.slug]))
        seasons = [label for label, _ in page.context["upcoming_seasons"]]
        self.assertIn(f"{TODAY.year + 1}–{(TODAY.year + 2) % 100:02d}", seasons)  # the January game's season
        self.assertEqual([[e.name for e in events] for _, events in page.context["past_seasons"]], [["Old game"]])
        self.assertContains(page, "Past dates (1)")
        self.assertContains(page, "Happens several times a year, usually September, October")
