"""Typed choices T1 (docs/plans/typed-choices.md): a "choose one" knows what it's about, its options ask for
that kind's fields, and the box shows each option's line."""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.core.testing import RestoringTransactionTestCase
from apps.locations.models import City, Country, POI
from apps.trips.forms import OptionForm, OptionGroupForm
from apps.trips.models import Day, Option, OptionGroup, Trip, TripGrant, TripRole
from apps.trips.quick_add import choice_kind

User = get_user_model()


class GuessTests(SimpleTestCase):
    def test_the_prompt_says_what_it_is(self):
        for text, expected in (("Where to stay in Munich", {"kind": "stay"}), ("Augsburg hotel", {"kind": "stay"}),
                               ("Dinner Friday", {"kind": "eat", "meal_type": "dinner"}),
                               ("Lunch or brunch", {"kind": "eat", "meal_type": "lunch"}),
                               ("Train or drive to Füssen", {"kind": "travel", "mode": "train"}),
                               ("How to get to the airport", {"kind": "travel"}),
                               ("Old town walk or museum", {"kind": "do"}), ("Afternoon", {"kind": "do"})):
            self.assertEqual(choice_kind(text), expected, text)


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED, currency_code="EUR")
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48, longitude=11,
                                          approval_status=ApprovalStatus.APPROVED)
        self.trip.cities.add(self.munich)
        self.keller = POI.objects.create(name="Augustiner Keller", slug="augustiner", city=self.munich, latitude=48,
                                         longitude=11, approval_status=ApprovalStatus.APPROVED, poi_type_id="food")
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18), city=self.munich)

    def group(self, kind="stay", **extra):
        return OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Where to stay", kind=kind, **extra)


class FormTests(Fixture):
    def fields(self, kind):
        return set(OptionForm(trip=self.trip, kind=kind).fields) - {"title", "notes", "url", "est_cost", "currency",
                                                                    "order", "cost_basis", "cost_people", "rooms"}

    def test_each_kind_asks_for_its_fields(self):
        self.assertEqual(self.fields("stay"), {"city", "poi", "place_text", "nights"})
        self.assertEqual(self.fields("eat"), {"poi", "place_text"})
        self.assertEqual(self.fields("do"), {"poi", "activity", "event", "place_text"})
        self.assertEqual(self.fields("travel"), {"from_text", "to_text"})
        self.assertEqual(self.fields("any"), set())
        # What the cost means (budget-estimates B1): a stay's options offer the stay bases, per night first.
        stay = OptionForm(trip=self.trip, kind="stay")
        self.assertEqual([v for v, _ in stay.fields["cost_basis"].choices][1:], ["night", "room_night", "person_night", "total"])
        self.assertIn("rooms", stay.fields)
        self.assertNotIn("rooms", OptionForm(trip=self.trip, kind="eat").fields)
        self.assertEqual(list(OptionForm(trip=self.trip, kind="eat").fields["poi"].queryset), [self.keller])

    def test_one_catalogue_link_at_most(self):
        form = OptionForm({"title": "x", "poi": self.keller.pk, "city": self.munich.pk, "currency": "EUR"},
                          trip=self.trip, kind="stay")
        self.assertFalse(form.is_valid())
        self.assertIn("Link one catalogue item at most", str(form.errors))

    def test_the_group_keeps_only_its_kinds_fields(self):
        form = OptionGroupForm({"prompt": "Dinner", "kind": "eat", "meal_type": "dinner", "start_time": "19:30",
                                "nights": "3", "mode": "train", "end_time": "21:00"})
        self.assertTrue(form.is_valid(), form.errors)
        group = form.save(commit=False)
        self.assertEqual((group.meal_type, group.start_time, group.nights, group.mode, group.end_time),
                         ("dinner", time(19, 30), None, "", None))
        form = OptionGroupForm({"prompt": "Tour", "kind": "do", "start_time": "11:00", "end_time": "10:00"})
        self.assertIn("Until must be after", str(form.errors))


class LineTests(Fixture):
    def test_a_stay_costs_per_night(self):
        group = self.group(nights=3)
        rugs = Option.objects.create(group=group, title="Rugs Hotel", est_cost=Decimal("95"), currency="EUR",
                                     place_text="Maximilianstraße")
        flat = Option.objects.create(group=group, title="Flat", est_cost=Decimal("80"), currency="EUR", nights=4)
        self.assertEqual((rugs.own_cost, flat.own_cost), (Decimal("285"), Decimal("320")))
        self.assertEqual(rugs.kind_line(), "EUR 95.00/night × 3 = EUR 285.00 · Maximilianstraße")
        group.nights = None
        group.save()
        rugs.refresh_from_db()
        self.assertEqual((rugs.own_cost, rugs.kind_line()), (Decimal("95"), "EUR 95.00/night · Maximilianstraße"))

    def test_each_kinds_line(self):
        eat = self.group("eat", meal_type="dinner", start_time=time(19, 30))
        self.assertEqual(Option.objects.create(group=eat, title="Keller", poi=self.keller, est_cost=40,
                                               currency="EUR").kind_line(), "Augustiner Keller · EUR 40.00")
        do = self.group("do", start_time=time(11), end_time=time(16))
        self.assertEqual(Option.objects.create(group=do, title="Tent", place_text="Hacker-Festzelt").kind_line(),
                         "Hacker-Festzelt · 11:00–16:00")
        travel = self.group("travel", mode="train")
        self.assertEqual(Option.objects.create(group=travel, title="RE", from_text="Augsburg", to_text="Munich",
                                               est_cost=12, currency="EUR").kind_line(),
                         "Train · Augsburg → Munich · EUR 12.00")
        self.assertEqual(Option.objects.create(group=self.group("any"), title="x", est_cost=5).kind_line(), "")

    def test_the_box_shows_the_line_and_the_total_counts(self):
        group = self.group(nights=2)
        Option.objects.create(group=group, title="Rugs Hotel", est_cost=Decimal("95"), currency="EUR",
                              place_text="Maximilianstraße")
        Option.objects.create(group=group, title="Flat", est_cost=Decimal("80"), currency="EUR")
        from apps.accounts.models import AccountSettings
        AccountSettings.objects.update_or_create(user=self.viewer, defaults={"preferred_currency": "EUR"})
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("EUR 95.00/night × 2 = EUR 190.00 · Maximilianstraße", html)
        self.assertIn("EUR 190.00", html)  # the option's cost is the total
        self.assertIn("data-choice-kind>Stay · 2 nights", html)
        group.pick(group.options.get(title="Rugs Hotel"))
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn("EUR 190.00", html[html.index('id="cost-estimate"'):])  # the estimate takes the total


class ViewTests(Fixture):
    def test_add_options_guesses_the_kind(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:quick_add", args=[self.trip.pk, self.day.pk]),
                         {"text": "Dinner Friday", "kind": "options"})
        group = OptionGroup.objects.get()
        self.assertEqual((group.prompt, group.kind, group.meal_type), ("Dinner Friday", "eat", "dinner"))

    def test_choose_one_guesses_and_the_page_can_change_it(self):
        self.client.force_login(self.editor)
        new = reverse("trips:group_new", args=[self.trip.pk, self.day.pk])
        page = self.client.get(new, {"prompt": "Where to stay"})
        self.assertEqual(page.context["form"].instance.kind, "stay")
        self.assertEqual(self.client.get(new, {"prompt": "Where to stay", "kind": "do"}).context["form"].instance.kind,
                         "do")
        group = self.group("stay", nights=2)
        url = reverse("trips:group_edit", args=[self.trip.pk, group.pk])
        page = self.client.get(url)
        self.assertIn("nights", page.context["formset"].forms[0].fields)
        data = {"prompt": "Where to stay", "kind": "do", "nights": "2", "start_time": "11:00", "end_time": "",
                "notes": "", "order": "", "meal_type": "", "mode": "",
                "options-TOTAL_FORMS": "0", "options-INITIAL_FORMS": "0"}
        response = self.client.post(url + "?next=/x/", data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(url))  # a changed kind stays on the page
        group.refresh_from_db()
        self.assertEqual((group.kind, group.nights, group.start_time), ("do", None, time(11)))
        self.assertIn("activity", self.client.get(url).context["formset"].forms[0].fields)

    def test_the_pickers_load_once_for_every_row(self):
        group = self.group("do")
        Option.objects.create(group=group, title="First")  # the per-option items lists load once there's one
        self.client.force_login(self.editor)
        url = reverse("trips:group_edit", args=[self.trip.pk, group.pk])

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(url)
            return len(ctx.captured_queries)
        count()
        before = count()
        for n in range(4):
            Option.objects.create(group=group, title=f"Option {n}")
        self.assertEqual(count(), before)  # the pickers and items load once, not per row

    def test_the_trip_page_costs_no_more_queries(self):
        """The option's catalogue link comes with it (select_related): the page's count is unchanged."""
        group = self.group("eat", meal_type="dinner")
        Option.objects.create(group=group, title="Keller", poi=self.keller)
        self.client.force_login(self.viewer)
        url = reverse("trips:trip_detail", args=[self.trip.pk])
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        before = len(ctx.captured_queries)
        for n in range(3):
            Option.objects.create(group=group, title=f"More {n}", poi=self.keller)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        self.assertEqual(len(ctx.captured_queries), before)


class MigrationTests(RestoringTransactionTestCase):
    """trips 0052: existing choices become "Anything" and keep everything."""

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        nodes = [(app, target if app == "trips" else name) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_groups_are_any(self):
        apps = self.migrate("0051_retire_old_section_types")
        Trip = apps.get_model("trips", "Trip")
        Day = apps.get_model("trips", "Day")
        Group = apps.get_model("trips", "OptionGroup")
        Option = apps.get_model("trips", "Option")
        trip = Trip.objects.create(name="Old", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        day = Day.objects.create(trip=trip, day_number=1, date=date(2027, 1, 1))
        group = Group.objects.create(trip=trip, day=day, prompt="Afternoon", start_time=time(14))
        option = Option.objects.create(group=group, title="Castle", notes="Up the hill", est_cost=8, currency="EUR")
        apps = self.migrate("0052_choice_kinds")
        group = apps.get_model("trips", "OptionGroup").objects.get(pk=group.pk)
        option = apps.get_model("trips", "Option").objects.get(pk=option.pk)
        self.assertEqual((group.kind, group.start_time, group.nights), ("any", time(14), None))
        self.assertEqual((option.title, option.notes, option.est_cost, option.place_text, option.made_id),
                         ("Castle", "Up the hill", 8, "", None))
