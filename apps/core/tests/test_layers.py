import importlib.util

from django.conf import settings
from django.test import SimpleTestCase


def load_check_layers():
    path = settings.BASE_DIR / "scripts" / "check_layers.py"
    spec = importlib.util.spec_from_file_location("check_layers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DependencyLayerTests(SimpleTestCase):
    """Fails when an app imports up the layer table in CLAUDE.md."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.check_layers = load_check_layers()

    def test_no_layer_violations(self):
        violations = self.check_layers.find_violations()
        self.assertEqual(violations, [], "\n" + "\n".join(violations))

    def test_flags_upward_import(self):
        self.assertTrue(self.check_layers.check_import("core", "apps.trips.models", ["Trip"]))

    def test_flags_concrete_user_import(self):
        self.assertTrue(self.check_layers.check_import("trips", "apps.accounts.models", ["User"]))

    def test_allows_listed_same_layer_import(self):
        self.assertEqual(self.check_layers.check_import("events", "apps.locations.models", ["City"]), [])

    def test_flags_unprefixed_local_import(self):
        self.assertTrue(self.check_layers.check_import("trips", "locations.models", ["City"]))

    def test_allows_third_party_and_django_imports(self):
        self.assertEqual(self.check_layers.check_import("trips", "django.apps", ["apps"]), [])

    def test_flags_app_directories_outside_apps(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["theme/apps.py", "stray/apps.py", "apps/core/apps.py", "apps/newapp/apps.py"]:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            problems = self.check_layers.check_layout(root)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any(p.startswith("stray/") for p in problems))
        self.assertTrue(any(p.startswith("apps/newapp/") for p in problems))
