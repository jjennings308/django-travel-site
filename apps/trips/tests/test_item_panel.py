"""The item panel on the trip page (docs/plans/day-first-planning.md, P2): every item's page renders
without the site chrome with ?panel=1, readers get a read-only view, a save comes back to the panel,
and one day can be fetched on its own to swap in."""
from datetime import date, time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (Comment, Day, Lodging, Meal, Section, TransportLeg, Trip, TripActivity, TripGrant,
                               TripRole)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18), theme="Arrival")
        self.day2 = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19))
        self.leg = TransportLeg.objects.create(trip=self.trip, date=self.day.date, origin="Munich",
                                               destination="Salzburg", mode="train")
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", check_in=self.day.date,
                                           check_out=date(2027, 9, 20))
        self.activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Salt mine tour",
                                                    start_time=time(14, 0))
        self.meal = Meal.objects.create(day=self.day, name="Augustiner", meal_type="dinner",
                                        reserved_time=time(19, 30))
        self.section = Section.objects.create(day=self.day, section_type="note", title="Heads up",
                                              content={"tone": "warning", "paragraphs": ["Cash only."]})

    def edit_urls(self):
        t = self.trip.pk
        return {
            "leg": reverse("trips:leg_edit", args=[t, self.leg.pk]),
            "stay": reverse("trips:stay_edit", args=[t, self.stay.pk]),
            "activity": reverse("trips:activity_edit", args=[t, self.day.pk, self.activity.pk]),
            "meal": reverse("trips:meal_edit", args=[t, self.day.pk, self.meal.pk]),
            "section": reverse("trips:section_edit", args=[t, self.day.pk, self.section.pk]),
            "day": reverse("trips:day_edit", args=[t, self.day.pk]),
        }

    def item_pk(self, kind):
        return {"leg": self.leg, "stay": self.stay, "activity": self.activity, "meal": self.meal,
                "section": self.section, "day": self.day}[kind].pk


class PanelPageTests(Fixture):
    def test_every_item_page_renders_without_the_chrome(self):
        self.client.force_login(self.editor)
        for kind, url in self.edit_urls().items():
            with self.subTest(kind=kind):
                page = self.client.get(url, {"panel": "1"})
                self.assertEqual(page.status_code, 200)
                html = page.content.decode()
                self.assertNotIn("<html", html)
                self.assertNotIn("<header", html)
                self.assertIn("data-panel-page", html)
                self.assertIn('data-panel-tab="details', html)
                self.assertIn("<html", self.client.get(url).content.decode())  # on its own, as before

    def test_the_tabs(self):
        self.client.force_login(self.editor)
        urls = self.edit_urls()
        leg = self.client.get(urls["leg"], {"panel": "1"}).content.decode()
        for tab in ("details", "booking", "contacts"):
            self.assertIn(f'data-panel-tab="{tab}', leg)
        activity = self.client.get(urls["activity"], {"panel": "1"}).content.decode()
        self.assertIn('data-panel-tab="people"', activity)  # its travellers
        Comment.objects.create(content_object=self.section, author=self.viewer, body="Bring euros")
        section = self.client.get(urls["section"], {"panel": "1"}).content.decode()
        self.assertIn('data-panel-tab="comments"', section)
        self.assertIn("Bring euros", section)
        self.assertNotIn("Bring euros", self.client.get(urls["section"]).content.decode())  # panel only
        day = self.client.get(urls["day"], {"panel": "1"}).content.decode()
        self.assertNotIn('id="on-this-day"', day)  # just the day's details in the panel
        self.assertIn('id="on-this-day"', self.client.get(urls["day"]).content.decode())

    def test_access_is_unchanged(self):
        for kind, url in self.edit_urls().items():
            with self.subTest(kind=kind):
                self.client.force_login(self.viewer)
                self.assertEqual(self.client.get(url, {"panel": "1"}).status_code, 403)
                self.client.force_login(self.stranger)
                self.assertEqual(self.client.get(url, {"panel": "1"}).status_code, 404)

    def test_a_save_comes_back_to_the_panel(self):
        self.client.force_login(self.editor)
        url = self.edit_urls()["meal"]
        here = url + "?panel=1"
        response = self.client.post(f"{url}?panel=1&next={here}", {
            "name": "Augustiner Bräustuben", "meal_type": "dinner", "reserved_time": "20:00", "cuisine": "",
            "price_range": "", "why_recommended": "", "reservation_notes": "", "poi": "", "order": ""},
            follow=True)
        self.assertEqual(response.redirect_chain[-1][0], here)
        self.assertContains(response, "Saved Augustiner Bräustuben.")
        self.assertNotContains(response, "<html")
        self.meal.refresh_from_db()
        self.assertEqual(self.meal.reserved_time, time(20, 0))

    def test_deleting_goes_to_next(self):
        self.client.force_login(self.editor)
        back = reverse("trips:trip_detail", args=[self.trip.pk])
        for url, model, pk in (
                (reverse("trips:meal_delete", args=[self.trip.pk, self.day.pk, self.meal.pk]), Meal, self.meal.pk),
                (reverse("trips:section_delete", args=[self.trip.pk, self.day.pk, self.section.pk]), Section,
                 self.section.pk)):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url, {"next": back}), f'value="{back}"')
                self.assertRedirects(self.client.post(url, {"next": back}), back, fetch_redirect_response=False)
                self.assertFalse(model.objects.filter(pk=pk).exists())

    def test_a_section_save_honours_next(self):
        self.client.force_login(self.editor)
        url = self.edit_urls()["section"]
        back = reverse("trips:trip_detail", args=[self.trip.pk]) + f"#section-{self.section.pk}"
        response = self.client.post(url + "?next=" + back.replace("#", "%23"), {
            "title": "Heads up", "icon": "", "order": "0", "tone": "warning", "text": "Cards too."})
        self.assertRedirects(response, back, fetch_redirect_response=False)


class ReadOnlyPanelTests(Fixture):
    def url(self, kind, pk=None):
        return reverse("trips:item_panel", args=[self.trip.pk, kind, pk or self.item_pk(kind)])

    def test_readers_see_each_item_without_edit_links(self):
        self.client.force_login(self.viewer)
        for kind, text in (("leg", "Munich → Salzburg"), ("stay", "Hotel Laimer Hof"), ("activity", "Salt mine tour"),
                           ("meal", "Augustiner"), ("section", "Cash only."), ("day", "Arrival")):
            with self.subTest(kind=kind):
                page = self.client.get(self.url(kind), {"panel": "1"})
                self.assertContains(page, text)
                self.assertNotContains(page, "<html")
                self.assertNotContains(page, ">Edit<")

    def test_notes_where_the_item_has_them(self):
        Comment.objects.create(content_object=self.day, author=self.editor, body="Meet at the station")
        self.client.force_login(self.viewer)
        page = self.client.get(self.url("day"), {"panel": "1"})
        self.assertContains(page, 'data-panel-tab="comments"')
        self.assertContains(page, "Meet at the station")
        self.assertNotContains(self.client.get(self.url("leg"), {"panel": "1"}), 'data-panel-tab="comments"')

    def test_strangers_unknown_kinds_and_other_trips(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url("leg")).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("trips:item_panel", args=[self.trip.pk, "trip", 1])).status_code, 404)
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        foreign = TransportLeg.objects.create(trip=other, origin="A", destination="B", date=date(2027, 1, 1))
        self.assertEqual(self.client.get(self.url("leg", foreign.pk)).status_code, 404)


class TripPageTests(Fixture):
    def page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def test_editors_open_edit_pages_readers_the_read_only_view(self):
        editor, viewer = self.page(self.editor), self.page(self.viewer)
        for kind, url in self.edit_urls().items():
            if kind == "day":
                continue
            with self.subTest(kind=kind):
                self.assertIn(f'data-panel="{url}"', editor)
                self.assertIn(f'data-panel="{reverse("trips:item_panel", args=[self.trip.pk, kind, self.item_pk(kind)])}"',
                              viewer)
                self.assertNotIn(f'data-panel="{url}"', viewer)
        self.assertIn("data-panel-link>Edit this day</a>", editor)
        for html in (editor, viewer):
            self.assertIn('id="item-panel"', html)
            self.assertIn("trips/panel.js", html)
        self.assertIn("locations/city_search.js", editor)  # the city box works inside the panel
        self.assertNotIn("locations/city_search.js", viewer)
        self.assertTrue((Path(settings.BASE_DIR) / "apps/trips/static/trips/panel.js").exists())

    def test_meals_have_their_own_page_now(self):
        self.assertIn(reverse("trips:meal_edit", args=[self.trip.pk, self.day.pk, self.meal.pk]) + "?next=",
                      self.page(self.editor))


class DayFragmentTests(Fixture):
    def url(self, day=None):
        return reverse("trips:day_fragment", args=[self.trip.pk, (day or self.day).pk])

    def test_one_day_open_with_its_items(self):
        self.client.force_login(self.viewer)
        html = self.client.get(self.url()).content.decode()
        self.assertIn('id="day-1" open', html)
        for anchor in (f"leg-{self.leg.pk}", f"activity-{self.activity.pk}", f"meal-{self.meal.pk}",
                       f"section-{self.section.pk}", f"stay-{self.stay.pk}"):
            self.assertIn(f'id="{anchor}"', html)
        self.assertNotIn("<html", html)
        self.assertNotIn('id="day-2"', html)
        self.assertIn('id="day-2"', self.client.get(self.url(self.day2)).content.decode())

    def test_its_links_come_back_to_the_trip_page_not_the_fragment(self):
        self.client.force_login(self.editor)
        html = self.client.get(self.url()).content.decode()
        trip_path = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertIn(f"?next={trip_path}%23day-1", html)
        self.assertNotIn("?next=" + self.url(), html)

    def test_access(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.viewer)
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripGrant.objects.create(trip=other, user=self.viewer, role=TripRole.VIEWER)
        self.assertEqual(self.client.get(reverse("trips:day_fragment", args=[other.pk, self.day.pk])).status_code, 404)


class MealPageTests(Fixture):
    def test_viewers_cant_and_the_page_has_confirmations_and_contacts(self):
        url = reverse("trips:meal_edit", args=[self.trip.pk, self.day.pk, self.meal.pk])
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.editor)
        page = self.client.get(url)
        self.assertContains(page, reverse("trips:item_confirmations", args=[self.trip.pk, "meal", self.meal.pk]))
        self.assertContains(page, reverse("trips:item_links", args=[self.trip.pk, "meal", self.meal.pk]))
