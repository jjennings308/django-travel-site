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
        self.assertTrue(self.check_layers.check_import("core", "trips.models", ["Trip"]))

    def test_flags_concrete_user_import(self):
        self.assertTrue(self.check_layers.check_import("trips", "accounts.models", ["User"]))

    def test_allows_listed_same_layer_import(self):
        self.assertEqual(self.check_layers.check_import("events", "locations.models", ["City"]), [])
