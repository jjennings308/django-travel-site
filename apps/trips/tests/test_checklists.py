"""Checklists (site roadmap R9)."""
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips import checklists
from apps.trips.models import Checklist, ChecklistItem, ChecklistTick, Traveler, Trip, TripGrant, TripRole

User = get_user_model()


class ChecklistFixture(TestCase):
    def setUp(self):
        self.ed = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.co = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.vi = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 5, 10), end_date=date(2027, 5, 14),
                                        created_by=self.ed)
        for user, role in ((self.ed, TripRole.EDITOR), (self.co, TripRole.COMMENTOR), (self.vi, TripRole.VIEWER)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.james = Traveler.objects.create(name="James")
        self.regan = Traveler.objects.create(name="Regan")
        self.trip.travelers.set([self.james, self.regan])
        self.docs = Checklist.objects.create(trip=self.trip, title="Documents", kind="documents")
        self.passport = ChecklistItem.objects.create(checklist=self.docs, text="Passport", per_person=True, order=0)
        self.insurance = ChecklistItem.objects.create(checklist=self.docs, text="Insurance", order=1)
        self.page = reverse("trips:trip_detail", args=[self.trip.pk])

    def tick(self, item, done=True, traveler=None, user=None, background=False):
        self.client.force_login(user or self.co)
        data = {"done": "1" if done else "0"}
        if traveler:
            data["traveler"] = traveler.pk
        headers = {"HTTP_X_REQUESTED_WITH": "fetch"} if background else {}
        return self.client.post(reverse("trips:checklist_tick", args=[self.trip.pk, item.pk]), data, **headers)


class TickTests(ChecklistFixture):
    def test_per_person_ticks(self):
        response = self.tick(self.passport, traveler=self.james)
        self.assertRedirects(response, f"{self.page}#checklist-{self.docs.pk}", fetch_redirect_response=False)
        tick = ChecklistTick.objects.get()
        self.assertEqual((tick.traveler, tick.ticked_by), (self.james, self.co))
        self.tick(self.passport, traveler=self.james)  # twice is still once
        self.assertEqual(ChecklistTick.objects.count(), 1)
        self.tick(self.passport, done=False, traveler=self.james)
        self.assertFalse(ChecklistTick.objects.exists())

    def test_shared_item_and_background_post(self):
        self.assertEqual(self.tick(self.insurance, background=True).status_code, 204)
        self.insurance.refresh_from_db()
        self.assertIsNotNone(self.insurance.done_at)
        self.assertEqual(self.insurance.done_by, self.co)
        self.tick(self.insurance, done=False)
        self.insurance.refresh_from_db()
        self.assertIsNone(self.insurance.done_at)

    def test_a_traveller_not_on_the_trip_is_refused(self):
        stranger = Traveler.objects.create(name="Stranger")
        self.assertEqual(self.tick(self.passport, traveler=stranger).status_code, 404)

    def test_per_person_without_a_roster_acts_shared(self):
        self.trip.travelers.clear()
        self.tick(self.passport)
        self.passport.refresh_from_db()
        self.assertIsNotNone(self.passport.done_at)

    def test_permissions(self):
        self.assertEqual(self.tick(self.insurance, user=self.vi).status_code, 403)
        stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.assertEqual(self.tick(self.insurance, user=stranger).status_code, 404)
        other = Trip.objects.create(name="Paris", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripGrant.objects.create(trip=other, user=self.co, role=TripRole.COMMENTOR)
        self.client.force_login(self.co)
        url = reverse("trips:checklist_tick", args=[other.pk, self.insurance.pk])
        self.assertEqual(self.client.post(url, {"done": "1"}).status_code, 404)


class PageTests(ChecklistFixture):
    def test_trip_page_shows_boxes_per_traveller(self):
        ChecklistTick.objects.create(item=self.passport, traveler=self.james)
        self.client.force_login(self.co)
        html = self.client.get(self.page).content.decode()
        self.assertIn(f'id="checklist-{self.docs.pk}"', html)
        self.assertIn("☑</span> James", html)
        self.assertIn("☐</span> Regan", html)
        self.assertIn("data-tick", html)
        self.assertIn("0/2 done", html)

    def test_viewers_see_ticks_without_buttons(self):
        self.client.force_login(self.vi)
        html = self.client.get(self.page).content.decode()
        self.assertIn("Passport", html)
        self.assertNotIn("data-tick", html)
        self.assertNotIn(reverse("trips:checklist_edit", args=[self.trip.pk, self.docs.pk]), html)

    def test_needs_attention_only_in_the_two_weeks_before(self):
        lists = checklists.attach(Trip.objects.prefetch_related("checklists__items__ticks", "travelers")
                                  .get(pk=self.trip.pk))
        trip = self.trip
        self.assertEqual(checklists.attention(trip, lists, today=date(2027, 4, 1)), 0)
        self.assertEqual(checklists.attention(trip, lists, today=date(2027, 4, 30)), 3)  # 2 passports + insurance
        self.assertEqual(checklists.attention(trip, lists, today=date(2027, 5, 15)), 0)  # trip over

    def test_never_public(self):
        self.trip.enable_public()
        html = self.client.get(reverse("public_trip", args=[self.trip.public_token])).content.decode()
        self.assertNotIn("Passport", html)


class EditTests(ChecklistFixture):
    def test_editors_make_and_edit_lists(self):
        self.client.force_login(self.ed)
        edit_page = self.client.get(reverse("trips:trip_settings", args=[self.trip.pk]))
        self.assertContains(edit_page, "Start from a template")
        response = self.client.post(reverse("trips:checklist_new", args=[self.trip.pk]), {
            "title": "Packing", "kind": "packing",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-text": "Charger", "items-0-per_person": "on", "items-0-order": "0",
            "items-1-text": "", "items-1-order": "0",
        })
        self.assertEqual(response.status_code, 302)
        packing = Checklist.objects.get(title="Packing")
        self.assertEqual([(i.text, i.per_person) for i in packing.items.all()], [("Charger", True)])

    def test_only_editors(self):
        self.client.force_login(self.co)
        self.assertEqual(self.client.get(reverse("trips:checklist_edit", args=[self.trip.pk, self.docs.pk])).status_code,
                         403)
        self.assertEqual(self.client.post(reverse("trips:checklist_from_template", args=[self.trip.pk]),
                                          {"template": "rail"}).status_code, 403)

    def test_delete(self):
        ChecklistTick.objects.create(item=self.passport, traveler=self.james)
        self.client.force_login(self.ed)
        self.client.post(reverse("trips:checklist_delete", args=[self.trip.pk, self.docs.pk]))
        self.assertFalse(Checklist.objects.filter(pk=self.docs.pk).exists())
        self.assertFalse(ChecklistTick.objects.exists())


class TemplateTests(ChecklistFixture):
    def test_every_template_parses(self):
        files = sorted(checklists.TEMPLATE_DIR.glob("*.md"))
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            with self.subTest(template=path.name):
                parsed = checklists.parse(path)
                self.assertTrue(parsed["items"])
        self.assertEqual(len(checklists.templates()), len(files))

    def test_start_from_a_template(self):
        self.client.force_login(self.ed)
        response = self.client.post(reverse("trips:checklist_from_template", args=[self.trip.pk]),
                                    {"template": "international"})
        made = Checklist.objects.get(title="International trip")
        self.assertRedirects(response, reverse("trips:checklist_edit", args=[self.trip.pk, made.pk]))
        self.assertEqual(made.kind, "documents")
        first = made.items.first()
        self.assertTrue(first.per_person)
        self.assertTrue(first.text.startswith("Passport"))
        self.assertFalse(made.items.get(text="Some local cash for the first day").per_person)

    def test_unknown_template_is_a_404(self):
        self.client.force_login(self.ed)
        self.assertEqual(self.client.post(reverse("trips:checklist_from_template", args=[self.trip.pk]),
                                          {"template": "../../etc"}).status_code, 404)

    def test_bad_template_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.md"
            bad.write_text("title: X\nkind: luggage\nsummary: y\n\n- a\n", encoding="utf-8")
            with self.assertRaises(checklists.TemplateError):
                checklists.parse(bad)
            bad.write_text("title: X\nkind: packing\nsummary: y\n\nnot a list line\n", encoding="utf-8")
            with self.assertRaises(checklists.TemplateError):
                checklists.parse(bad)
