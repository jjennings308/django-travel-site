"""One rewards-membership model (site roadmap R11): trips.RewardsMembership keyed to the traveller,
linked to the rewards catalogue; the old per-account model's rows were copied across."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import RestoringTransactionTestCase
from apps.rewards.models import RewardsProgram
from apps.trips.models import RewardsMembership, Traveler

User = get_user_model()


class CopyMigrationTests(RestoringTransactionTestCase):
    BEFORE = [("trips", "0041_membership_catalogue_program"),
              ("rewards", "0002_remove_rewardsprogram_rewards_program_unique_name_company_and_more")]
    AFTER = [("trips", "0042_copy_user_rewards_memberships"), ("rewards", "0003_delete_userrewardsmembership")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_copies_merges_and_skips(self):
        apps = self.migrate(self.BEFORE)
        Account = apps.get_model("accounts", "User")
        Traveler = apps.get_model("trips", "Traveler")
        Program = apps.get_model("rewards", "RewardsProgram")
        Old = apps.get_model("rewards", "UserRewardsMembership")
        New = apps.get_model("trips", "RewardsMembership")
        james = Account.objects.create(username="j_mig", email="j_mig@example.com", password="x")
        nobody = Account.objects.create(username="n_mig", email="n_mig@example.com", password="x")
        traveler = Traveler.objects.create(name="James", user=james)
        delta, _ = Program.objects.get_or_create(name="SkyMiles", company="Delta Air Lines",
                                                 defaults={"program_type": "airline"})
        db, _ = Program.objects.get_or_create(name="BahnBonus", company="Deutsche Bahn",
                                              defaults={"program_type": "train"})
        # Typed on the profile already, as people type it.
        New.objects.create(traveler=traveler, program="Delta SkyMiles", member_number="", kind="airline")
        Old.objects.create(user=james, program=delta, member_number="9001", current_tier="Gold",
                           points_balance=1200)
        Old.objects.create(user=james, program=db, member_number="X" * 60)
        Old.objects.create(user=nobody, program=db, member_number="7")  # no traveller: skipped

        apps = self.migrate(self.AFTER)
        New = apps.get_model("trips", "RewardsMembership")
        rows = {m.program: m for m in New.objects.filter(traveler__name="James")}
        self.assertEqual(sorted(rows), ["Delta SkyMiles", "Deutsche Bahn BahnBonus"])
        merged = rows["Delta SkyMiles"]
        self.assertEqual((merged.member_number, merged.tier, merged.catalogue_program_id), ("9001", "Gold", delta.pk))
        self.assertIn("Points: 1200", merged.notes)
        rail = rows["Deutsche Bahn BahnBonus"]
        self.assertEqual((rail.kind, rail.member_number), ("rail", "X" * 40))
        self.assertIn("Full member number: " + "X" * 60, rail.notes)
        self.assertEqual(New.objects.count(), 2)
        self.assertNotIn("user_rewards_memberships", connection.introspection.table_names())


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")
        self.traveler = Traveler.objects.get(user=self.user)
        self.program, _ = RewardsProgram.objects.get_or_create(name="SkyMiles", company="Delta Air Lines",
                                                               defaults={"program_type": "airline"})
        self.client.force_login(self.user)
        self.url = reverse("trips:traveler_profile")

    def post(self, row):
        data = {"memberships-TOTAL_FORMS": "1", "memberships-INITIAL_FORMS": "0", "memberships-MIN_NUM_FORMS": "0",
                "memberships-MAX_NUM_FORMS": "1000", **{f"memberships-0-{k}": v for k, v in row.items()}}
        page = self.client.get(self.url)
        form = page.context["form"]
        for name, field in form.fields.items():
            value = form.initial.get(name, field.initial)
            if value not in (None, "") and name not in data:
                data[name] = value
        return self.client.post(self.url, data)

    def test_pick_from_the_catalogue_fills_name_and_kind(self):
        self.post({"catalogue_program": str(self.program.pk), "kind": "other", "member_number": "123"})
        membership = RewardsMembership.objects.get(traveler=self.traveler)
        self.assertEqual((membership.program, membership.kind, membership.catalogue_program),
                         ("Delta Air Lines SkyMiles", "airline", self.program))

    def test_catalogue_page_prefills_the_blank_row(self):
        response = self.client.get(self.url, {"program": self.program.pk})
        formset = response.context["memberships"]
        self.assertEqual(formset.forms[-1].initial.get("catalogue_program"), self.program.pk)

    def test_old_rewards_pages_redirect_to_the_profile(self):
        for name, args in (("rewards:dashboard", []), ("rewards:memberships_list", []),
                           ("rewards:add_membership", [])):
            response = self.client.get(reverse(name, args=args), {"program": self.program.pk})
            self.assertRedirects(response, f"{self.url}?program={self.program.pk}#memberships",
                                 fetch_redirect_response=False)

    def test_catalogue_pages_still_work_and_link_to_the_profile(self):
        self.assertEqual(self.client.get(reverse("rewards:programs_browse")).status_code, 200)
        detail = self.client.get(reverse("rewards:program_detail", args=[self.program.pk]))
        self.assertContains(detail, f"{self.url}?program={self.program.pk}#memberships")

    def test_memberships_stay_private(self):
        RewardsMembership.objects.create(traveler=self.traveler, program="Delta SkyMiles", member_number="SECRET1")
        other = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        self.client.force_login(other)
        self.assertNotContains(self.client.get(self.url), "SECRET1")
        self.assertNotContains(self.client.get(reverse("rewards:program_detail", args=[self.program.pk])), "SECRET1")
