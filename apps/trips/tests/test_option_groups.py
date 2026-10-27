""""Choose one" groups, options and votes (docs/plans/day-first-planning.md, P4)."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from apps.trips import calendar, changes, day_first
from apps.trips.booking_tasks import not_booked
from apps.trips.forms import BookingTaskForm, TripActivityForm
from apps.trips.models import (BookingTask, Comment, Confirmation, Day, Lodging, Option, OptionGroup, Section,
                               TaskOption, TransportLeg, Trip, TripActivity, TripChange, TripGrant, TripRole, Vote)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd", first_name="Ed")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd", first_name="Cora")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor, home_currency="EUR")
        for user, role in ((self.editor, TripRole.EDITOR), (self.viewer, TripRole.VIEWER),
                           (self.commentor, TripRole.COMMENTOR)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Afternoon")
        self.castle = Option.objects.create(group=self.group, title="Castle", est_cost=8, currency="EUR", order=0)
        self.museum = Option.objects.create(group=self.group, title="Deutsches Museum", order=1)
        self.tour = TripActivity.objects.create(trip=self.trip, day=self.day, title="Castle tour", kind="tour",
                                                start_time=time(14, 0), end_time=time(16, 0), est_cost=20,
                                                currency="EUR", option=self.castle)
        self.exhibit = TripActivity.objects.create(trip=self.trip, day=self.day, title="Museum entry", kind="entry",
                                                   start_time=time(14, 0), option=self.museum)
        self.train = TransportLeg.objects.create(trip=self.trip, date=self.day.date, origin="Munich",
                                                 destination="Füssen", mode="train", operator="DB", option=self.castle)
        self.lunch = TripActivity.objects.create(trip=self.trip, day=self.day, title="Lunch walk", kind="other")

    def page(self, user=None):
        self.client.force_login(user or self.editor)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def timeline(self, html):
        start = html.index('id="day-1"')
        return html[start:html.index("</details>", start)]


class WhatCountsTests(Fixture):
    def test_undecided_items_are_only_in_the_box(self):
        html = self.timeline(self.page())
        box = html[html.index('id="group-'):]
        self.assertIn("Castle tour", box)
        self.assertIn("Museum entry", box)
        self.assertIn("Undecided", box)
        self.assertIn("EUR 28.00", box)  # castle: its own 8 + the tour's 20
        self.assertIn("~2 h", box)  # the tour's time
        outside = html[:html.index('id="group-')]
        self.assertNotIn("Castle tour", outside)
        self.assertIn("Lunch walk", outside)

    def test_nothing_undecided_counts_anywhere_until_picked(self):
        def counted():
            trip = Trip.objects.get(pk=self.trip.pk)
            ics = calendar.build(trip).decode()
            self.client.force_login(self.editor)
            page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
            booked = {entry["item"].pk for entry in page.context["not_booked"]
                      if isinstance(entry["item"], TripActivity)}
            return {
                "calendar": {name for name in ("Castle tour", "Museum entry", "Lunch walk", "Füssen") if name in ics},
                "not booked": {a.title for a in TripActivity.objects.filter(pk__in=booked)},
                "estimate": page.context["cost_estimate"],
                "undecided event": "Undecided: Castle / Deutsches Museum" in ics,
            }

        from django.apps import apps  # the estimate is in the reader's currency
        apps.get_model("accounts", "AccountSettings").objects.update_or_create(
            user=self.editor, defaults={"preferred_currency": "EUR"})
        before = counted()
        self.assertEqual(before["calendar"], {"Lunch walk"})
        self.assertEqual(before["not booked"], set())
        self.assertIsNone(before["estimate"])
        self.assertTrue(before["undecided event"])
        self.group.pick(self.castle, self.editor)
        after = counted()
        self.assertEqual(after["calendar"], {"Castle tour", "Lunch walk", "Füssen"})
        self.assertEqual(after["not booked"], {"Castle tour"})
        self.assertEqual(str(after["estimate"]["total"]), "28.00")  # the tour's 20 + the option's own 8
        self.assertFalse(after["undecided event"])

    def test_the_map_counts_only_decided_legs_and_stays(self):
        from apps.locations.models import City, Country
        from apps.approval_system.models import ApprovalStatus
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        munich, fussen = (City.objects.create(name=n, slug=n.lower(), country=de, latitude=1, longitude=1,
                                              approval_status=ApprovalStatus.APPROVED) for n in ("Munich", "Fussen"))
        TransportLeg.objects.filter(pk=self.train.pk).update(origin_city=munich, destination_city=fussen)
        Lodging.objects.create(trip=self.trip, name="Castle inn", check_in=self.day.date, check_out=date(2027, 9, 19),
                               latitude=1, longitude=1, option=self.castle)
        self.client.force_login(self.viewer)
        url = reverse("trips:trip_map_data", args=[self.trip.pk])
        layers = lambda: [f["properties"]["layer"] for f in self.client.get(url).json()["features"]]  # noqa: E731
        self.assertNotIn("legs", layers())
        self.assertNotIn("stays", layers())
        self.group.pick(self.castle)
        self.assertIn("legs", layers())
        self.assertIn("stays", layers())

    def test_an_undecided_group_counts_in_the_days_warning_and_the_banner(self):
        html = self.page()
        self.assertIn("⚠1", self.timeline(html))
        self.assertIn(f'data-decisions href="#group-{self.group.pk}">1 decision</a>', html)
        self.group.pick(self.museum)
        html = self.page()
        self.assertNotIn("data-decisions", html)
        self.assertIn("Chosen from:", self.timeline(html))
        self.assertIn("Museum entry", self.timeline(html))


class PickTests(Fixture):
    def test_pick_and_reopen_never_delete(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:option_pick", args=[self.trip.pk, self.castle.pk]))
        self.group.refresh_from_db()
        self.assertEqual((self.group.state, self.group.decided_by), ("picked", self.editor))
        self.assertEqual(list(Option.objects.filter(chosen=True)), [self.castle])
        self.client.post(reverse("trips:option_pick", args=[self.trip.pk, self.museum.pk]))
        self.assertEqual(list(Option.objects.filter(chosen=True)), [self.museum])
        self.client.post(reverse("trips:group_reopen", args=[self.trip.pk, self.group.pk]))
        self.group.refresh_from_db()
        self.assertEqual((self.group.state, Option.objects.filter(chosen=True).count()), ("open", 0))
        self.assertEqual(Option.objects.count(), 2)

    def test_editors_only(self):
        for user in (self.viewer, self.commentor):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("trips:option_pick", args=[self.trip.pk, self.castle.pk])).status_code, 403)
        self.client.force_login(User.objects.create_user("x", "x@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.post(reverse("trips:option_pick", args=[self.trip.pk, self.castle.pk])).status_code, 404)

    def test_history_and_undo_reopens(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:option_pick", args=[self.trip.pk, self.castle.pk]))
        change = TripChange.objects.filter(item_type="optiongroup").latest("pk")
        self.assertIn("picked Castle", change.summary)
        self.assertTrue(changes.can_undo(change, changes.latest_change_ids(self.trip)))
        changes.undo(change)
        self.group.refresh_from_db()
        self.assertEqual((self.group.state, Option.objects.filter(chosen=True).count()), ("open", 0))
        reopened = TripChange.objects.filter(item_type="optiongroup").latest("pk")
        self.assertFalse(changes.can_undo(reopened, changes.latest_change_ids(self.trip)))


class VoteTests(Fixture):
    def test_one_vote_each_shown_to_everyone(self):
        url = reverse("trips:option_vote", args=[self.trip.pk, self.castle.pk])
        self.client.force_login(self.commentor)
        self.client.post(url)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(url, HTTP_X_REQUESTED_WITH="fetch").status_code, 204)
        self.assertEqual(Vote.objects.filter(option=self.castle).count(), 2)
        box = self.timeline(self.page(self.viewer))
        self.assertIn("👍 2", box)
        self.assertIn("Cora, Ed", box)
        self.client.force_login(self.commentor)
        self.client.post(url)  # takes it back
        self.assertEqual(Vote.objects.filter(option=self.castle).count(), 1)

    def test_viewers_cant_vote(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("trips:option_vote", args=[self.trip.pk, self.castle.pk])).status_code, 403)
        self.assertNotIn("data-vote", self.timeline(self.page(self.viewer)))


class EditingTests(Fixture):
    def test_a_new_group_with_options_and_an_item_added_into_one(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:group_new", args=[self.trip.pk, self.day.pk]), {
            "prompt": "Dinner", "start_time": "19:00", "notes": "", "order": "",
            "options-TOTAL_FORMS": "2", "options-INITIAL_FORMS": "0",
            "options-0-title": "Augustiner", "options-0-currency": "EUR",
            "options-1-title": "Hofbräuhaus", "options-1-currency": "EUR"})
        group = OptionGroup.objects.get(prompt="Dinner")
        self.assertRedirects(response, reverse("trips:group_edit", args=[self.trip.pk, group.pk]) + "?next="
                             + f"/trips/{self.trip.pk}/%23day-1", fetch_redirect_response=False)
        self.assertEqual([o.title for o in group.options.all()], ["Augustiner", "Hofbräuhaus"])
        option = group.options.first()
        page = self.client.get(reverse("trips:group_edit", args=[self.trip.pk, group.pk]))
        self.assertContains(page, "data-add-to-option")
        here = reverse("trips:group_edit", args=[self.trip.pk, group.pk])
        self.client.post(reverse("trips:quick_add", args=[self.trip.pk, self.day.pk]),
                         {"text": "Dinner Augustiner 7pm", "option": option.pk, "next": here})
        self.assertEqual(option.meals.get().reserved_time, time(19, 0))
        self.assertIn("Dinner", self.timeline(self.page()))  # the group's box, at 7 PM

    def test_the_in_option_field_appears_once_the_day_has_options(self):
        form = TripActivityForm(instance=self.lunch, trip=self.trip)
        self.assertEqual(list(form.fields["option"].queryset), [self.castle, self.museum])
        other = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19))
        quiet = TripActivity.objects.create(trip=self.trip, day=other, title="Nothing to choose")
        self.assertNotIn("option", TripActivityForm(instance=quiet, trip=self.trip).fields)

    def test_deleting_a_group_keeps_its_items_on_the_day(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:group_delete", args=[self.trip.pk, self.group.pk]))
        self.assertFalse(OptionGroup.objects.exists())
        self.tour.refresh_from_db()
        self.assertIsNone(self.tour.option)
        self.assertIn("Castle tour", self.timeline(self.page()))

    def test_plus_add_options(self):
        self.client.force_login(self.editor)
        reply = self.client.post(reverse("trips:quick_add", args=[self.trip.pk, self.day.pk]),
                                 {"text": "Evening", "kind": "options"}, HTTP_X_REQUESTED_WITH="fetch").json()
        group = OptionGroup.objects.get(prompt="Evening")
        self.assertEqual(reply, {"url": reverse("trips:group_edit", args=[self.trip.pk, group.pk]),
                                 "anchor": f"group-{group.pk}"})

    def test_todo_lists_open_groups_and_new_todos_are_bookings(self):
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("trips:trip_todo", args=[self.trip.pk]))
        self.assertContains(page, "Decide: <a")
        self.assertContains(page, "Castle / Deutsches Museum")
        self.assertEqual([value for value, _ in BookingTaskForm(trip=self.trip).fields["kind"].choices], ["book"])
        old = BookingTask.objects.create(trip=self.trip, title="Which hotel", kind="decide")
        self.assertIn("decide", [v for v, _ in BookingTaskForm(instance=old, trip=self.trip).fields["kind"].choices])

    def test_readers_open_an_item_in_an_option(self):
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("trips:item_panel", args=[self.trip.pk, "activity", self.tour.pk]), {"panel": 1})
        self.assertContains(page, "Castle tour")


class ConvertTests(Fixture):
    def test_a_choose_your_adventure_section_becomes_a_group(self):
        section = Section.objects.create(day=self.day, section_type="choose_your_adventure", title="Morning", order=3,
                                         content={"prompt": "Pick one", "summary": "Both short.", "options": [
                                             {"letter": "A", "title": "Lake", "description": "Swim", "duration": "2 h",
                                              "cost": "€8"}, {"title": "Old town", "description": "Stroll"}]})
        Comment.objects.create(content_object=section, author=self.commentor, body="Lake!")
        (day, items), = day_first.plan(self.trip)
        self.assertEqual(items[0].after, ("Choose one", ["Pick one (undecided)", "• Lake — Swim\n2 h · €8",
                                                         "• Old town — Stroll"]))
        self.assertEqual(day_first.apply(self.trip), 1)
        group = OptionGroup.objects.get(prompt="Pick one")
        self.assertEqual((group.notes, group.order, group.state), ("Both short.", 3, "open"))
        self.assertEqual([(o.title, o.notes) for o in group.options.all()],
                         [("Lake", "Swim\n2 h · €8"), ("Old town", "Stroll")])
        self.assertFalse(Section.objects.filter(pk=section.pk).exists())
        comment = Comment.objects.get(body="Lake!")
        self.assertEqual((comment.content_type, comment.object_id), (ContentType.objects.get_for_model(Day), self.day.pk))

    def test_one_with_a_confirmation_becomes_a_note_with_its_links(self):
        """Retire-old-section-types S1: a confirmation can't cover a whole choice, so the section becomes a
        note on the same row, keeping its confirmation, comments and contacts; nothing is left over."""
        from apps.trips.models import Contact, ItemLink
        section = Section.objects.create(day=self.day, section_type="choose_your_adventure", title="Tour", order=2,
                                         content={"prompt": "Which tour?", "summary": "Booked as one.", "source": "docx",
                                                  "options": [{"title": "A", "description": "Boat", "duration": "2 h",
                                                               "cost": "€30"}, {"title": "B"}, "junk"]})
        confirmation = Confirmation.objects.create(trip=self.trip, confirmation_number="X1")
        confirmation.link(section)
        Comment.objects.create(content_object=section, author=self.commentor, body="Boat!")
        ItemLink.link(Contact.objects.create(trip=self.trip, name="Captain"), section)
        (day, items), = day_first.plan(self.trip)
        self.assertEqual(items[0].before, ("Choose your adventure", ["Which tour?", "• A", "• B"]))
        self.assertEqual(items[0].after, ("Note", ["Which tour?", "Booked as one.", "• A — Boat (2 h · €30)", "• B"]))
        self.assertEqual(day_first.apply(self.trip), 1)
        section.refresh_from_db()
        self.assertEqual((section.section_type, section.title, section.order), ("note", "Which tour?", 2))
        self.assertEqual(section.content, {"source": "docx", "tone": "",
                                           "paragraphs": ["Booked as one.", "• A — Boat (2 h · €30)", "• B"]})
        self.assertEqual(list(confirmation.links.values_list("object_id", flat=True)), [section.pk])
        self.assertTrue(Comment.objects.filter(body="Boat!", object_id=section.pk).exists())
        self.assertTrue(ItemLink.objects.filter(target_id=section.pk).exists())
        self.assertFalse(OptionGroup.objects.filter(prompt="Which tour?").exists())
        self.assertEqual(day_first.plan(self.trip), [])

    def test_a_decision_todo_becomes_a_picked_group_on_its_day(self):
        stay_day = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19))
        stay = Lodging.objects.create(trip=self.trip, name="Augusta", check_in=stay_day.date, check_out=date(2027, 9, 21))
        task = BookingTask.objects.create(trip=self.trip, title="Augsburg hotel", kind="decide", stay=stay)
        TaskOption.objects.create(task=task, title="Augusta", detail="Old town", url="https://example.com/a",
                                  est_cost=140, currency="EUR", chosen=True, order=0)
        TaskOption.objects.create(task=task, title="Drei Mohren", est_cost=210, currency="EUR", order=1)
        loose = BookingTask.objects.create(trip=self.trip, title="Which tour", kind="decide")
        TaskOption.objects.create(task=loose, title="Bike")
        plan = dict(day_first.plan(self.trip))
        self.assertEqual(plan[self.day][-1].flag, "no day of its own: put on Day 1, check it")
        day_first.apply(self.trip, [f"task-{task.pk}"])
        group = OptionGroup.objects.get(prompt="Augsburg hotel")
        self.assertEqual((group.day, group.state), (stay_day, "picked"))
        chosen = group.options.get(chosen=True)
        self.assertEqual((chosen.title, chosen.notes, chosen.url, chosen.est_cost), ("Augusta", "Old town",
                                                                                      "https://example.com/a", 140))
        task.refresh_from_db()
        self.assertTrue(task.done)
        self.assertIn("Moved to the choice “Augsburg hotel” on Day 2.", task.notes)
        self.assertEqual(task.options.count(), 2)  # still readable

    def test_the_banner_counts_them(self):
        Section.objects.create(day=self.day, section_type="choose_your_adventure", content={"options": []})
        task = BookingTask.objects.create(trip=self.trip, title="Hotel?", kind="decide")
        TaskOption.objects.create(task=task, title="A")
        self.assertIn("2 to convert to notes and choices", self.page())


class BookletTests(Fixture):
    def test_undecided_prints_its_options_picked_prints_the_choice(self):
        from unittest import mock
        self.client.force_login(self.viewer)
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF-"
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        self.assertIn("Afternoon — undecided", captured["html"])
        self.assertIn("Castle tour", captured["html"])
        self.group.pick(self.museum)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        self.assertNotIn("undecided", captured["html"])
        self.assertIn("<strong>Afternoon:</strong> Deutsches Museum", captured["html"])
        self.assertNotIn("Castle tour", captured["html"])


class PublicViewTests(Fixture):
    def test_nothing_undecided_is_public(self):
        from apps.trips.models import Meal
        Meal.objects.create(day=self.day, name="Undecided dinner", meal_type="dinner", option=self.castle)
        Meal.objects.create(day=self.day, name="Booked lunch", meal_type="lunch")
        self.trip.enable_public()
        html = self.client.get(reverse("public_trip", args=[self.trip.public_token])).content.decode()
        self.assertIn("Booked lunch", html)
        self.assertNotIn("Undecided dinner", html)
        for word in ("Castle", "Afternoon", "Undecided", "👍"):
            self.assertNotIn(word, html)
