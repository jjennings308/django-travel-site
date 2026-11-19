"""One warm palette (docs/plans/ux-consistency.md, V1): the committed stylesheet re-points the trips pages' zinc greys
at the warm ones, warm-500 is dark enough for body text, the white-text buttons pass contrast, and the dead CSS and
config files stay gone."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BUILT = Path(settings.BASE_DIR) / "theme/static/css/dist/styles.css"
SOURCE = Path(settings.BASE_DIR) / "theme/static_src/src/styles.css"


def luminance(hex_colour):
    channels = [int(hex_colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def theme_colour(css, name):
    found = re.search(rf"--color-{name}:\s*(#[0-9a-fA-F]{{6}})", css)
    return found.group(1) if found else None


class BuiltStylesheetTests(SimpleTestCase):
    def setUp(self):
        self.css = BUILT.read_text()

    def test_trips_zinc_reads_the_warm_palette(self):
        remap = re.search(r"\.trips-ui\{(--color-zinc-50:[^}]*)\}", self.css)
        self.assertIsNotNone(remap, "the .trips-ui zinc remap is missing from the built CSS")
        for shade in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900):
            self.assertIn(f"--color-zinc-{shade}:var(--color-warm-{shade})", remap.group(1))
            self.assertIn(f"--color-warm-{shade}:", self.css)  # each target is defined
        # The remap only works while utilities read the variable rather than an inlined value.
        self.assertIn(".text-zinc-500{color:var(--color-zinc-500)}", self.css)

    def test_secondary_text_passes_contrast(self):
        warm_500 = theme_colour(self.css, "warm-500")
        self.assertEqual(warm_500.lower(), "#786a5f")
        for background in (theme_colour(self.css, "warm-50"), "#ffffff"):
            self.assertGreaterEqual(contrast(warm_500, background), 4.5, background)


class SourceTests(SimpleTestCase):
    def test_white_text_buttons_pass_contrast(self):
        source = SOURCE.read_text()
        accent = re.search(r"\.sbl-btn-accent \{ @apply bg-([\w-]+) text-white", source).group(1)
        self.assertEqual(accent, "earth-ochre-dark")
        self.assertGreaterEqual(contrast(theme_colour(source, accent), "#ffffff"), 4.5)

    def test_sidebar_group_labels_are_readable(self):
        sidebar = (Path(settings.BASE_DIR) / "templates/partials/_sidebar.html").read_text()
        step = re.search(r'step="([^"]*)"', sidebar).group(1)
        self.assertIn("text-warm-600", step)
        self.assertNotIn("text-warm-400", step)

    def test_dead_style_files_stay_gone(self):
        base = Path(settings.BASE_DIR)
        for path in (
            "apps/core/static/core/css/design-system.css",
            "apps/core/static/core/css/design-system chat.css",
            "apps/core/static/core/css/design-system claude.css",
            "apps/core/static/core/css/site.css",
            "theme/static_src/tailwind.config.js",
            "templates/components/home_example.html",
        ):
            self.assertFalse((base / path).exists(), path)
