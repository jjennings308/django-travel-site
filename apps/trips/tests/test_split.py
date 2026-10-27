"""Splitting a "choose one" between travellers (docs/plans/day-first-planning.md, P5)."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips import calendar, changes
from apps.trips.forms import SplitForm
from apps.trips.models import (Lodging, Meal, Option, OptionGroup, Section, TransportLeg, Traveler, Trip,
                               TripActivity, TripChange, counts_q)

from .test_option_groups import Fixture

User = get_user_model()


class SplitFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.debbie = Traveler.objects.create(name="Debbie")
        self.john = Traveler.objects.create(name="John")
        self.ed = Traveler.objects.get(user=self.editor)
        self.ed.name = "Ed"
        self.ed.save()
        self.trip.travelers.set([self.debbie, self.john, self.ed])
        self.url = reverse("trips:group_split", args=[self.trip.pk, self.group.pk])

    def split(self, **who):
        """split(castle=[debbie], museum=[john, ed])"""
        options = {"castle": self.castle, "museum": self.museum}
        self.group.split({options[name]: people for name, people in who.items()}, self.editor)

    def post(self, placed):
        self.client.force_login(self.editor)
        return self.client.post(self.url, {f"t{t.pk}": option.pk for t, option in placed.items()})


class AssignmentTests(SplitFixture):
    def test_everyone_is_placed_once(self):
        response = self.post({self.debbie: self.castle, self.john: self.museum, self.ed: self.museum})
        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.state, OptionGroup.State.SPLIT)
        self.assertEqual(list(self.castle.travelers.all()), [self.debbie])
        self.assertEqual(set(self.museum.travelers.all()), {self.john, self.ed})
        self.assertEqual(self.group.decided_by, self.editor)
        self.assertFalse(Option.objects.filter(chosen=True).exists())

    def test_nobody_left_out(self):
        response = self.post({self.debbie: self.castle, self.john: self.museum})
        self.assertContains(response, "Choose where Ed goes.")
        self.assertEqual(OptionGroup.objects.get().state, OptionGroup.State.OPEN)

    def test_everyone_on_one_option_is_a_pick(self):
        response = self.post({self.debbie: self.castle, self.john: self.castle, self.ed: self.castle})
        self.assertContains(response, "pick it instead")

    def test_a_split_needs_two_people(self):
        self.trip.travelers.set([self.ed])
        form = SplitForm({f"t{self.ed.pk}": self.castle.pk}, group=self.group, travelers=[self.ed])
        self.assertFalse(form.is_valid())
        self.assertIn("at least two people", str(form.errors))

    def test_the_days_own_roster_decides_who_is_split(self):
        self.day.travelers.set([self.debbie, self.john])
        self.client.force_login(self.editor)
        page = self.client.get(self.url).content.decode()
        self.assertIn("Debbie", page)
        self.assertNotIn(">Ed<", page)
        self.assertEqual(self.post({self.debbie: self.castle, self.john: self.museum}).status_code, 302)

    def test_resplitting_moves_people_and_prefills(self):
        self.split(castle=[self.debbie, self.john], museum=[self.ed])
        self.client.force_login(self.editor)
        form = self.client.get(self.url).context["form"]
        self.assertEqual(form[f"t{self.john.pk}"].initial, self.castle.pk)
        self.post({self.debbie: self.castle, self.john: self.museum, self.ed: self.museum})
        self.assertEqual(list(self.castle.travelers.all()), [self.debbie])

    def test_editors_only(self):
        self.client.force_login(self.commentor)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_split_is_in_the_history_and_undo_reopens(self):
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        change = TripChange.objects.filter(item_type="optiongroup").latest("pk")
        self.assertIn("split: Debbie → Castle", change.summary)
        changes.undo(change)
        self.assertEqual(OptionGroup.objects.get().state, OptionGroup.State.OPEN)


class WhatCountsTests(SplitFixture):
    def test_every_taken_option_counts(self):
        Option.objects.create(group=self.group, title="Nap", order=2)
        nap = TripActivity.objects.create(trip=self.trip, day=self.day, title="Nap", kind="other",
                                          option=Option.objects.get(title="Nap"))
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        counted = set(TripActivity.objects.filter(counts_q()).values_list("title", flat=True))
        self.assertEqual(counted, {"Castle tour", "Museum entry", "Lunch walk"})
        self.assertNotIn(nap.title, counted)  # nobody takes it: Considered
        self.assertEqual(TransportLeg.objects.filter(counts_q()).count(), 1)

    def test_the_estimate_adds_both_tracks(self):
        from django.apps import apps
        apps.get_model("accounts", "AccountSettings").objects.update_or_create(
            user=self.editor, defaults={"preferred_currency": "EUR"})
        self.museum.est_cost, self.museum.currency = 14, "EUR"
        self.museum.save()
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        self.client.force_login(self.editor)
        estimate = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).context["cost_estimate"]
        # castle 8 + tour 20 + museum 14
        self.assertEqual(str(estimate["total"]), "42.00")


class TracksOnThePageTests(SplitFixture):
    def test_tracks_with_names_and_shared_items_outside(self):
        Meal.objects.create(day=self.day, name="Augustiner", meal_type="dinner", reserved_time=time(19, 30))
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        html = self.timeline(self.page())
        box = html[html.index("data-split-group"):]
        box = box[:box.index("Reopen the choice")]
        self.assertEqual(box.count("data-track>"), 2)
        self.assertIn("Debbie", box)
        self.assertIn("Ed, John", box)  # travellers in name order
        self.assertIn("Castle tour", box)
        self.assertIn("Füssen", box)
        self.assertIn("Museum entry", box)
        self.assertIn("EUR 28.00", box)  # the castle track's cost
        outside = html.replace(box, "")
        outside = outside[outside.index("day-body"):]  # the summary line's highlights may name either track
        self.assertNotIn("Castle tour", outside)
        self.assertIn("Lunch walk", outside)
        self.assertIn("Augustiner", outside)  # after the split, together again
        self.assertLess(html.index("data-split-group"), html.index("Augustiner"))

    def test_a_tracks_notes_and_stay_are_in_it(self):
        Section.objects.create(day=self.day, section_type="note", title="Meet at the gate", option=self.castle,
                               content={"tone": "", "paragraphs": ["By the fountain"]})
        Lodging.objects.create(trip=self.trip, name="Hotel Füssen", check_in=self.day.date,
                               check_out=date(2027, 9, 20), option=self.castle)
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        html = self.timeline(self.page())
        box = html[html.index("data-split-group"):html.index("Reopen the choice")]
        self.assertIn("Meet at the gate", box)
        self.assertIn("Hotel Füssen", box)
        self.assertEqual(html.count("Meet at the gate"), 1)
        day2 = self.page()
        self.assertNotIn("Sleeping: <a", self.timeline(day2))

    def test_split_link_for_editors(self):
        self.assertIn(f'href="{self.url}?next=', self.page())
        self.assertNotIn(self.url, self.page(self.commentor))


class CalendarTests(SplitFixture):
    def debbie_account(self):
        user = User.objects.create_user("deb", "deb@example.com", "pw-1234-abcd")
        Traveler.objects.filter(user=user).delete()  # the one every new account gets; Debbie is her
        self.debbie.user = user
        self.debbie.save()
        return user

    def ics(self, user):
        return calendar.build(Trip.objects.get(pk=self.trip.pk), user, mine=True).decode()

    def test_only_mine_follows_each_persons_track(self):
        debbie_user = self.debbie_account()
        Lodging.objects.create(trip=self.trip, name="Hotel Füssen", check_in=self.day.date,
                               check_out=date(2027, 9, 19), option=self.castle)
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        mine = self.ics(debbie_user)
        self.assertIn("Castle tour", mine)
        self.assertIn("Füssen", mine)
        self.assertIn("Hotel Füssen", mine)
        self.assertNotIn("Museum entry", mine)
        self.assertIn("Lunch walk", mine)  # shared
        ed = self.ics(self.editor)
        self.assertIn("Museum entry", ed)
        self.assertNotIn("Castle tour", ed)
        self.assertNotIn("Hotel Füssen", ed)
        everyone = calendar.build(Trip.objects.get(pk=self.trip.pk)).decode()
        self.assertIn("Castle tour", everyone)
        self.assertIn("Museum entry", everyone)
        self.assertNotIn("Undecided", everyone)

    def test_an_activitys_own_travellers_win(self):
        self.exhibit.travelers.set([self.debbie])
        debbie_user = self.debbie_account()
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        self.assertIn("Museum entry", self.ics(debbie_user))


class BookletTests(SplitFixture):
    def booklet(self):
        from unittest import mock
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"

        self.client.force_login(self.editor)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        return captured["html"]

    def test_two_tracks_side_by_side(self):
        self.split(castle=[self.debbie], museum=[self.john, self.ed])
        html = self.booklet()
        tracks = html[html.index('class="tracks"'):]
        tracks = tracks[:tracks.index("</table>")]
        self.assertEqual(tracks.count("<td"), 2)
        self.assertIn("Debbie", tracks)
        self.assertIn("Castle tour", tracks)
        self.assertIn("Museum entry", tracks)
        activities = html[html.index("<h3>Activities</h3>"):]
        self.assertNotIn("Castle tour", activities)
        self.assertIn("Lunch walk", activities)

    def test_more_tracks_are_stacked_with_names(self):
        third = Option.objects.create(group=self.group, title="Nap", order=2)
        self.group.split({self.castle: [self.debbie], self.museum: [self.john], third: [self.ed]})
        html = self.booklet()
        self.assertNotIn('class="tracks"', html)
        self.assertIn("— split", html)
        self.assertIn(">Ed</p>", html.replace("\n", ""))
