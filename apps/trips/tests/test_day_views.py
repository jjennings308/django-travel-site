"""Tests for the per-day editing views and the section payload forms.

Two things are being pinned here, and they are not the same kind of thing.

The first is access: a day and a section are reached *through* their trip, so
the trip's permission and 404 rules have to be inherited rather than re-decided.
A view that resolves a day on its own would let anyone who guessed an id edit a
day on a trip they cannot read.

The second is round-tripping. `Section.content` is a JSON blob written by
importers that know more than this UI does, so it can carry keys no form here
has a field for. A form that rebuilt the payload from its own fields would
silently drop those on the first save — the worst possible failure, because the
save looks like it worked and the data is gone. `SectionRoundTripTests` is the
regression net for that.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import TripRole
from apps.trips.forms import (
    ROW_CELL_SEPARATOR,
    section_payload_form,
    validate_day_roster,
)
from apps.trips.models import BookingTask, Day, Meal, Section, Trip

from apps.trips.tests.helpers import give

User = get_user_model()


def make_user(username, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", "pw-1234-abcd", **kwargs
    )


class DayEditingFixture(TestCase):
    def setUp(self):
        self.staff = make_user("root", is_staff=True, is_superuser=True)
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.trip = Trip.objects.create(
            name="Europe 2027",
            start_date=date(2027, 9, 25),
            end_date=date(2027, 10, 5),
            created_by=self.alice,
        )
        self.day = Day.objects.create(
            trip=self.trip, day_number=1, date=date(2027, 9, 25), theme="Fly to England"
        )
        # The role alone is not access: `visible_to` needs a grant *and* at
        # least viewer, so both have to be set or every test below is a 404.
        self.grant(self.alice, TripRole.EDITOR, trip=self.trip)

    def make_trip(self, name="Other trip"):
        return Trip.objects.create(
            name=name, start_date=date(2027, 1, 1), end_date=date(2027, 1, 5)
        )

    def grant(self, user, *roles, trip=None):
        return give(user, *roles, trip=trip, granted_by=self.staff)

    def day_payload(self, **overrides):
        data = {
            "day_number": 1,
            "date": "2027-09-25",
            "theme": "Fly to England",
            "meals_included": "",
            "travelers": [],
        }
        data.update(overrides)
        return data

    def meals_payload(self, rows=0, initial=0, **extra):
        data = {
            "meals-TOTAL_FORMS": rows,
            "meals-INITIAL_FORMS": initial,
            "meals-MIN_NUM_FORMS": 0,
            "meals-MAX_NUM_FORMS": 1000,
        }
        data.update(extra)
        return data


class DayCreateTests(DayEditingFixture):
    def url(self):
        return reverse("trips:day_create", args=[self.trip.pk])

    def test_an_editor_can_add_a_day(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.url(),
            self.day_payload(day_number=2, date="2027-09-26", theme="Marburg"),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        day = Day.objects.get(trip=self.trip, day_number=2)
        self.assertEqual(day.theme, "Marburg")
        self.assertEqual(day.travelers.count(), 0)

    def test_a_blank_roster_means_the_whole_group(self):
        self.client.force_login(self.alice)
        self.client.post(self.url(), self.day_payload(day_number=3))
        day = Day.objects.get(day_number=3)
        self.assertFalse(day.is_split)
        self.assertEqual(list(day.roster), list(self.trip.travelers.all()))

    def test_the_next_free_day_number_is_prefilled(self):
        self.client.force_login(self.alice)
        # Gaps matter: the prefill is max+1, not "count of days", so the
        # pre-existing day 1 in setUp plus these two make the answer 8.
        Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 28))
        Day.objects.create(trip=self.trip, day_number=7, date=date(2027, 10, 1))
        response = self.client.get(self.url())
        self.assertEqual(response.context["form"]["day_number"].initial, 8)

    def test_date_is_not_prefilled(self):
        # A wrong date prefill is a wrong date nobody notices. The day number is
        # safe to guess because the unique constraint complains if it is wrong.
        self.client.force_login(self.alice)
        response = self.client.get(self.url())
        self.assertIsNone(response.context["form"]["date"].initial)

    def test_a_viewer_cannot_reach_the_page(self):
        self.grant(make_user("vic"), TripRole.VIEWER, trip=self.trip)
        self.client.force_login(User.objects.get(username="vic"))
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_a_grantless_user_gets_404(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_logged_out_redirects(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_the_roster_only_offers_this_trip_s_travelers(self):
        from apps.trips.models import Traveler

        theirs = Traveler.objects.create(name="Stranger")
        self.make_trip().travelers.add(theirs)
        self.client.force_login(self.alice)
        response = self.client.get(self.url())
        queryset = response.context["form"].fields["travelers"].queryset
        self.assertNotIn(theirs, queryset)

    def test_a_duplicate_day_number_is_rejected(self):
        # setUp already made day 1.
        self.client.force_login(self.alice)
        response = self.client.post(self.url(), self.day_payload(day_number=1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Day.objects.filter(day_number=1).count(), 1)
        self.assertTrue(response.context["form"].errors)


class DayEditTests(DayEditingFixture):
    def url(self, pk=None):
        return reverse("trips:day_edit", args=[self.trip.pk, pk or self.day.pk])

    def test_an_editor_can_change_the_theme(self):
        self.client.force_login(self.alice)
        payload = self.day_payload(theme="Marburg", meals_included="")
        payload.update(self.meals_payload())
        response = self.client.post(self.url(), payload)
        self.assertEqual(response.status_code, 302)
        self.day.refresh_from_db()
        self.assertEqual(self.day.theme, "Marburg")

    def test_meals_save_with_the_day(self):
        self.client.force_login(self.alice)
        payload = self.day_payload()
        payload.update(
            self.meals_payload(
                rows=1,
                **{
                    "meals-0-name": "Café Central",
                    "meals-0-meal_type": Meal.MealType.SNACK,
                    "meals-0-cuisine": "Austrian",
                    "meals-0-price_range": "$$",
                    "meals-0-why_recommended": "Good cake",
                    "meals-0-reservation_notes": "",
                    "meals-0-order": "1",
                },
            )
        )
        response = self.client.post(self.url(), payload)
        self.assertEqual(response.status_code, 302)
        meal = Meal.objects.get()
        self.assertEqual(meal.name, "Café Central")
        self.assertEqual(meal.day, self.day)

    def test_the_untouched_blank_meal_row_is_not_saved(self):
        # extra=1 always leaves a blank row. Saving it as a row of empty strings
        # would put a nameless meal on every day.
        self.client.force_login(self.alice)
        payload = self.day_payload()
        payload.update(self.meals_payload(rows=1))
        self.client.post(self.url(), payload)
        self.assertEqual(Meal.objects.count(), 0)

    def test_a_bad_meal_writes_nothing_at_all(self):
        # A meal row is invalid, so the *day* must not be saved either. An
        # invalid choice is used rather than a missing name, because a wholly
        # empty row is skipped rather than rejected — that would pass this test
        # for the wrong reason.
        self.client.force_login(self.alice)
        payload = self.day_payload(theme="Should not stick")
        payload.update(
            self.meals_payload(
                rows=1,
                **{
                    "meals-0-name": "Somewhere",
                    "meals-0-meal_type": "brunch",
                    "meals-0-why_recommended": "Fine food",
                    "meals-0-order": "1",
                },
            )
        )
        response = self.client.post(self.url(), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["meal_formset"].errors)
        self.day.refresh_from_db()
        self.assertEqual(self.day.theme, "Fly to England")
        self.assertEqual(Meal.objects.count(), 0)

    def test_a_roster_naming_a_stranger_is_rejected(self):
        from apps.trips.models import Traveler

        stranger = Traveler.objects.create(name="Nobody")
        self.client.force_login(self.alice)
        payload = self.day_payload(travelers=[stranger.pk])
        payload.update(self.meals_payload())
        response = self.client.post(self.url(), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.day.travelers.count(), 0)

    def test_order_is_not_required_and_falls_back_to_the_default(self):
        # The model has a default of 0 but is not blank, so a form that left
        # `order` required would demand someone type a sort number to add a meal.
        self.client.force_login(self.alice)
        payload = self.day_payload()
        payload.update(
            self.meals_payload(
                rows=1,
                **{
                    "meals-0-name": "Somewhere",
                    "meals-0-meal_type": Meal.MealType.LUNCH,
                    "meals-0-why_recommended": "Good",
                },
            )
        )
        self.assertEqual(self.client.post(self.url(), payload).status_code, 302)
        self.assertEqual(Meal.objects.get().order, 0)

    def test_a_day_on_another_trip_is_404(self):
        other = self.make_trip("Taos")
        theirs = Day.objects.create(
            trip=other, day_number=1, date=date(2027, 1, 1)
        )
        self.client.force_login(self.alice)
        url = reverse("trips:day_edit", args=[self.trip.pk, theirs.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_viewer_cannot_edit(self):
        self.grant(make_user("vic"), TripRole.VIEWER, trip=self.trip)
        self.client.force_login(User.objects.get(username="vic"))
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_a_grantless_user_gets_404(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url()).status_code, 404)


class DayDeleteTests(DayEditingFixture):
    def url(self):
        return reverse("trips:day_delete", args=[self.trip.pk, self.day.pk])

    def test_get_only_confirms(self):
        Meal.objects.create(day=self.day, name="Café Central")
        Section.objects.create(day=self.day, section_type="phase", content={})
        self.client.force_login(self.alice)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Day.objects.filter(pk=self.day.pk).exists())
        self.assertEqual(response.context["meal_count"], 1)
        self.assertEqual(response.context["section_count"], 1)

    def test_post_deletes_the_day_and_its_content(self):
        Meal.objects.create(day=self.day, name="Café Central")
        section = Section.objects.create(day=self.day, section_type="phase", content={})
        self.client.force_login(self.alice)
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Day.objects.filter(pk=self.day.pk).exists())
        self.assertFalse(Meal.objects.filter(day_id=self.day.pk).exists())
        self.assertFalse(Section.objects.filter(pk=section.pk).exists())

    def test_a_linked_booking_task_survives(self):
        # BookingTask.day is SET_NULL precisely so tidying up a day does not
        # destroy the reasoning behind the task.
        task = BookingTask.objects.create(trip=self.trip, day=self.day, title="Book train")
        self.client.force_login(self.alice)
        self.client.post(self.url())
        task.refresh_from_db()
        self.assertIsNone(task.day_id)
        self.assertEqual(task.title, "Book train")

    def test_a_viewer_cannot_delete(self):
        self.grant(make_user("vic"), TripRole.VIEWER, trip=self.trip)
        self.client.force_login(User.objects.get(username="vic"))
        self.assertEqual(self.client.get(self.url()).status_code, 403)


class SectionViewTests(DayEditingFixture):
    def setUp(self):
        super().setUp()
        self.section = Section.objects.create(
            day=self.day,
            section_type=Section.Type.CALLOUT,
            content={"tone": "info", "text": "Original text"},
            order=0,
        )

    def create_url(self, section_type=Section.Type.CALLOUT):
        return reverse("trips:section_create", args=[self.trip.pk, self.day.pk, section_type])

    def edit_url(self, section=None):
        return reverse(
            "trips:section_edit", args=[self.trip.pk, self.day.pk, (section or self.section).pk]
        )

    # -- creating ---------------------------------------------------------

    def test_an_editor_can_add_a_callout(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.create_url(), {"title": "Tip", "icon": "", "order": "", "tone": "warning", "text": "Book ahead"}
        )
        self.assertEqual(response.status_code, 302)
        section = Section.objects.get(title="Tip")
        self.assertEqual(section.content, {"tone": "warning", "text": "Book ahead"})
        self.assertEqual(section.day, self.day)

    def test_the_type_comes_from_the_url_not_the_post(self):
        # A post claiming a different type must not get one: the payload form is
        # chosen from the type, so trusting a posted type would mean validating
        # one shape and saving another.
        self.client.force_login(self.alice)
        self.client.post(
            self.create_url(),
            {"section_type": Section.Type.PHASE, "tone": "info", "text": "Hi"},
        )
        created = Section.objects.exclude(pk=self.section.pk).get()
        self.assertEqual(created.section_type, Section.Type.CALLOUT)

    def test_an_unknown_type_in_the_url_is_404(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.create_url("interpretive_dance")).status_code, 404)

    def test_a_new_section_defaults_to_the_end_of_the_day(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.create_url(Section.Type.PHASE))
        self.assertEqual(response.context["section"].order, 1)

    # -- editing ----------------------------------------------------------

    def test_editing_rewrites_the_payload(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.edit_url(),
            {"title": "Tip", "icon": "⚠", "order": "2", "tone": "critical", "text": "Watch out"},
        )
        self.assertEqual(response.status_code, 302)
        self.section.refresh_from_db()
        self.assertEqual(self.section.content, {"tone": "critical", "text": "Watch out"})
        self.assertEqual(self.section.icon, "⚠")

    def test_an_invalid_tone_writes_nothing(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.edit_url(), {"title": "T", "order": "", "tone": "purple", "text": "x"}
        )
        self.assertEqual(response.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.content["text"], "Original text")

    def test_a_bad_title_writes_nothing(self):
        # The metadata and the payload are one save, so a long title must not
        # leave the payload rewritten.
        self.client.force_login(self.alice)
        response = self.client.post(
            self.edit_url(),
            {"title": "x" * 300, "order": "", "tone": "info", "text": "Changed"},
        )
        self.assertEqual(response.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.content["text"], "Original text")

    def test_a_section_on_another_day_is_404(self):
        other_day = Day.objects.create(
            trip=self.trip, day_number=2, date=date(2027, 9, 26)
        )
        theirs = Section.objects.create(day=other_day, section_type="phase", content={})
        self.client.force_login(self.alice)
        url = reverse("trips:section_edit", args=[self.trip.pk, self.day.pk, theirs.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_viewer_cannot_edit(self):
        self.grant(make_user("vic"), TripRole.VIEWER, trip=self.trip)
        self.client.force_login(User.objects.get(username="vic"))
        self.assertEqual(self.client.get(self.edit_url()).status_code, 403)

    def test_a_grantless_user_gets_404(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 404)

    # -- deleting ---------------------------------------------------------

    def test_delete_confirms_then_deletes(self):
        self.client.force_login(self.alice)
        url = reverse("trips:section_delete", args=[self.trip.pk, self.day.pk, self.section.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Section.objects.filter(pk=self.section.pk).exists())
        self.client.post(url)
        self.assertFalse(Section.objects.filter(pk=self.section.pk).exists())


class UnknownSectionTypeTests(DayEditingFixture):
    def test_an_unknown_type_renders_an_explanation_not_a_500(self):
        # A newer importer can write a type this UI has no form for. The row
        # still renders on the detail page, so refusing would make the day
        # unreachable through the only link that leads to it.
        section = Section.objects.create(
            day=self.day, section_type="some_future_type", content={"x": 1}
        )
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("trips:section_edit", args=[self.trip.pk, self.day.pk, section.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unsupported_type"], "some_future_type")

    def test_an_unknown_type_can_still_have_its_title_edited(self):
        section = Section.objects.create(
            day=self.day, section_type="some_future_type", content={"x": 1}
        )
        self.client.force_login(self.alice)
        self.client.post(
            reverse("trips:section_edit", args=[self.trip.pk, self.day.pk, section.pk]),
            {"title": "Renamed", "icon": "", "order": ""},
        )
        section.refresh_from_db()
        self.assertEqual(section.title, "Renamed")
        self.assertEqual(section.content, {"x": 1})


class LogisticsTableFormTests(TestCase):
    def test_columns_and_rows_round_trip(self):
        content = {"columns": ["Time", "Stop", "Details"], "rows": [["09:00", "Train", "ICE 51"]]}
        form = section_payload_form(
            "logistics_table",
            data={
                "columns": "Time\nStop\nDetails",
                "rows": "09:00" + ROW_CELL_SEPARATOR + "Train" + ROW_CELL_SEPARATOR + "ICE 51",
            },
            content=content,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), content)

    def test_a_row_with_the_wrong_cell_count_is_rejected(self):
        form = section_payload_form(
            "logistics_table",
            data={"columns": "Time\nStop", "rows": "09:00" + ROW_CELL_SEPARATOR + "Train\n10:00"},
            content={},
        )
        self.assertFalse(form.is_valid())
        # Named per row, because "one of your rows is wrong" is not actionable
        # when there are thirty of them.
        self.assertIn("Row 2", str(form.errors["rows"]))

    def test_a_four_column_table_works(self):
        content = {
            "columns": ["Leg", "Mode", "Time", "Notes"],
            "rows": [["1", "Train", "45 min", "window seat"]],
        }
        form = section_payload_form(
            "logistics_table",
            data={
                "columns": "Leg\nMode\nTime\nNotes",
                "rows": "1" + ROW_CELL_SEPARATOR + "Train" + ROW_CELL_SEPARATOR + "45 min" + ROW_CELL_SEPARATOR + "window seat",
            },
            content=content,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), content)


class ChooseYourAdventureFormTests(TestCase):
    OPTION_KEYS = ("letter", "title", "description", "duration", "cost")

    def payload(self, content=None, rows=0, **overrides):
        """A posted payload for a given stored `content`.

        Every stored option becomes a posted row, plus `rows` more, so a test can
        add options the way the page does. `overrides` sets individual fields —
        `overrides={"options-1-DELETE": "on"}` or
        `overrides={"options-0-cost": ""}`.
        """
        content = content or {}
        stored = content.get("options") or []
        total = max(len(stored), rows)
        data = {"prompt": content.get("prompt", "Pick one")}
        for index in range(total):
            option = stored[index] if index < len(stored) else {}
            for key in self.OPTION_KEYS:
                data[f"options-{index}-{key}"] = option.get(key, "")
        data["options-TOTAL_FORMS"] = total
        data["options-INITIAL_FORMS"] = len(stored)
        data["options-MIN_NUM_FORMS"] = 0
        data["options-MAX_NUM_FORMS"] = 1000
        data.update(overrides)
        return section_payload_form("choose_your_adventure", data=data, content=content)

    def test_a_half_typed_option_is_rejected_rather_than_saved_partially(self):
        # The regression: `clean()` used to forward only `non_form_errors`, so a
        # missing `title` did not invalidate the section and the option was
        # written to `content` without it — a save that looked like it worked.
        content = {
            "prompt": "Which castle?",
            "options": [
                {"letter": "A", "title": "Neuschwanstein", "description": "The famous one"},
                {"letter": "B", "title": "Linderhof", "description": "Quieter"},
            ],
        }
        form = self.payload(content, **{"options-1-title": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("Fix the highlighted options.", form.non_field_errors())
        self.assertIn("title", form.options.forms[1].errors)

    def test_the_untouched_blank_option_row_is_still_accepted(self):
        # The other side of the same fix: `extra=1` always renders one empty row,
        # and Django gives it `empty_permitted=True`, so refusing to save because
        # of it would break every save of this type.
        content = {
            "prompt": "Which castle?",
            "options": [
                {"letter": "A", "title": "Neuschwanstein", "description": "The famous one"},
                {"letter": "B", "title": "Linderhof", "description": "Quieter"},
            ],
        }
        form = self.payload(content, rows=1)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), content)

    def test_options_round_trip_including_the_letter_key(self):
        # `letter` is in the data but not in the module docstring's shape, which
        # is exactly why option keys are read off the data.
        content = {
            "prompt": "Which castle?",
            "options": [
                {"letter": "A", "title": "Neuschwanstein", "description": "The famous one"},
                {"letter": "B", "title": "Linderhof", "description": "Quieter"},
            ],
        }
        form = self.payload(content)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content(), content)

    def test_the_blank_extra_row_is_not_saved_as_an_option(self):
        content = {
            "prompt": "Pick one",
            "options": [{"letter": "A", "title": "One", "description": "First"}],
        }
        form = self.payload(content)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.to_content()["options"]), 1)

    def test_a_deleted_option_goes_away(self):
        content = {
            "prompt": "Pick one",
            "options": [
                {"letter": "A", "title": "One", "description": "First"},
                {"letter": "B", "title": "Two", "description": "Second"},
            ],
        }
        form = self.payload(content, **{"options-1-DELETE": "on"})
        self.assertTrue(form.is_valid(), form.errors)
        options = form.to_content()["options"]
        self.assertEqual([o["title"] for o in options], ["One"])

    def test_an_unknown_option_key_survives(self):
        content = {
            "prompt": "Pick one",
            "options": [{"title": "One", "description": "First", "booking_url": "http://x"}],
        }
        form = self.payload(content)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.to_content()["options"][0]["booking_url"], "http://x")

    def test_clearing_a_cost_removes_the_key(self):
        content = {
            "prompt": "Pick one",
            "options": [{"title": "One", "description": "First", "cost": "£20"}],
        }
        form = self.payload(content, **{"options-0-cost": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("cost", form.to_content()["options"][0])


class BlankOrderTests(DayEditingFixture):
    """A blank `order` must fall back to the model default, not to NULL.

    This is a browser-path bug, not a hand-written-payload one: HTML submits an
    empty string for a blank input, and `forms.IntegerField` turns that into
    `None`, which a `ModelForm` writes straight through as NULL against a NOT
    NULL column. Every model with an `order` here is affected, so the fix is
    shared and the test covers all three.
    """

    def test_a_blank_meal_order_saves(self):
        self.client.force_login(self.alice)
        payload = self.day_payload()
        payload.update(
            self.meals_payload(
                rows=1,
                **{
                    "meals-0-name": "Somewhere",
                    "meals-0-meal_type": Meal.MealType.LUNCH,
                    "meals-0-why_recommended": "Good",
                    "meals-0-order": "",
                },
            )
        )
        self.assertEqual(self.client.post(self.url(), payload).status_code, 302)
        self.assertEqual(Meal.objects.get().order, 0)

    def test_a_blank_section_order_saves(self):
        self.client.force_login(self.alice)
        url = reverse(
            "trips:section_create", args=[self.trip.pk, self.day.pk, Section.Type.CALLOUT]
        )
        response = self.client.post(
            url,
            {"title": "Tip", "icon": "", "order": "", "tone": "info", "text": "x"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Section.objects.get(title="Tip").order, 0)

    def test_a_blank_booking_task_order_saves(self):
        from apps.trips.forms import BookingTaskForm

        form = BookingTaskForm(
            data={
                "trip": self.trip.pk,
                "title": "Book the train",
                "priority": BookingTask.Priority.MEDIUM,
                "notes": "",
                "due": "",
                "due_note": "",
                "day": "",
                "confirmation": "",
                "done": "",
                "order": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["order"], 0)
        # commit=False because an inline formset normally sets `trip` on save;
        # standalone here, so the test does it.
        task = form.save(commit=False)
        task.trip = self.trip
        task.save()
        self.assertEqual(task.order, 0)

    def url(self):
        return reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])


class SectionRoundTripTests(TestCase):
    """Editing a section must not lose payload the UI has no field for.

    `Section.content` is written by importers that know more than this UI does,
    so it legitimately carries keys no form here has a field for. A form that
    rebuilt the payload from its own fields would drop those on the first save,
    and the worst part is that the save *looks* like it worked.

    These are the shapes taken from the real imported data, not invented ones.
    """

    def republish(self, section_type, content):
        """Post the payload form's own initial values back and return the result.

        That is exactly what a browser does when someone opens a section and
        presses save without changing anything, which is the case that must be a
        no-op.
        """
        form = section_payload_form(section_type, content=content)
        data = {
            name: (field.value() if hasattr(field, "value") else field)
            for name, field in form.initial.items()
        }
        if hasattr(form, "options"):
            keys = ("letter", "title", "description", "duration", "cost")
            for index, option_form in enumerate(form.options.forms):
                for key in keys:
                    data[f"options-{index}-{key}"] = option_form.initial.get(key, "")
            data["options-TOTAL_FORMS"] = len(form.options.forms)
            # The *stored* count, not the rendered count: `extra=1` renders one
            # blank row more than was saved, and the page posts
            # INITIAL_FORMS=len(stored) with TOTAL_FORMS=len(stored)+1. Claiming
            # the blank row already existed told the formset it was a real option
            # missing its title, which is exactly how an invalid option could be
            # saved — the helper had been hiding it.
            data["options-INITIAL_FORMS"] = len(content.get("options") or [])
        reposted = section_payload_form(section_type, data=data, content=content)
        self.assertTrue(reposted.is_valid(), reposted.errors)
        return reposted.to_content()

    def test_phase(self):
        content = {
            "heading": "Day 3 — Marburg",
            "summary": "A walking day along the Lahn.",
            "highlights": ["Sandstone quarries", "Landgrave's tomb"],
        }
        self.assertEqual(self.republish("phase", content), content)

    def test_callout(self):
        content = {"tone": "warning", "text": "Tents sell out in January."}
        self.assertEqual(self.republish("callout", content), content)

    def test_free_text(self):
        content = {"paragraphs": ["First paragraph.", "Second paragraph."]}
        self.assertEqual(self.republish("free_text", content), content)

    def test_two_column_logistics_table(self):
        content = {"columns": ["Detail", "Info"], "rows": [["Lunch", "€€"]]}
        self.assertEqual(self.republish("logistics_table", content), content)

    def test_three_column_logistics_table(self):
        content = {
            "columns": ["Time", "Stop", "Details"],
            "rows": [["09:00", "Train", "ICE 51"], ["11:30", "Marburg", "Old town"]],
        }
        self.assertEqual(self.republish("logistics_table", content), content)

    def test_four_column_logistics_table(self):
        content = {
            "columns": ["Leg", "Mode", "Time", "Notes"],
            "rows": [["1", "Train", "45 min", "window seat"]],
        }
        self.assertEqual(self.republish("logistics_table", content), content)

    def test_choose_your_adventure_with_letters(self):
        content = {
            "prompt": "Which castle?",
            "options": [
                {"letter": "A", "title": "Neuschwanstein", "description": "The famous one"},
                {"letter": "B", "title": "Linderhof", "description": "Quieter"},
            ],
        }
        self.assertEqual(self.republish("choose_your_adventure", content), content)

    def test_choose_your_adventure_with_extra_known_keys(self):
        # duration/cost are in the docstring's shape but not in the imported
        # rows, so they have to survive a save as well.
        content = {
            "prompt": "Pick",
            "options": [
                {
                    "letter": "A",
                    "title": "Rafting",
                    "description": "Class III",
                    "duration": "3 hrs",
                    "cost": "£40",
                }
            ],
        }
        self.assertEqual(self.republish("choose_your_adventure", content), content)

    def test_an_unknown_top_level_key_survives_every_type(self):
        for section_type, content in (
            ("phase", {"heading": "H", "summary": "S"}),
            ("callout", {"tone": "info", "text": "T"}),
            ("free_text", {"paragraphs": ["P"]}),
            ("logistics_table", {"columns": ["A"], "rows": [["b"]]}),
            ("choose_your_adventure", {"prompt": "P", "options": []}),
        ):
            with self.subTest(section_type=section_type):
                stored = dict(content, booking_url="https://example.com", version=3)
                self.assertEqual(self.republish(section_type, stored), stored)

    def test_a_missing_optional_key_is_not_invented(self):
        # The importers omit `highlights` when a phase has none. Adding an empty
        # list would render differently from omitting the key.
        content = {"heading": "H", "summary": "S"}
        self.assertEqual(self.republish("phase", content), content)
