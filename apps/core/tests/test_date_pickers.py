"""Every date, time and date-and-time field on the site's forms uses the browser's picker.

Imports every ``apps/*/forms.py``, builds each form defined there (so fields added in
``__init__`` count too; a form that can't be built without arguments is checked from its
``base_fields``) and fails on a field whose widget isn't one of ``apps.core.widgets``'
pickers with the right type and value format. The Django admin keeps its own widgets.
"""
import importlib
import inspect
from pathlib import Path

from django import forms
from django.conf import settings
from django.test import TestCase

from apps.core import widgets

PICKERS = {  # field kind -> (widget class, input type, value format)
    "date": (widgets.DateInput, "date", "%Y-%m-%d"),
    "time": (widgets.TimeInput, "time", "%H:%M"),
    "datetime": (widgets.DateTimeLocalInput, "datetime-local", "%Y-%m-%dT%H:%M"),
}

# "app.Form.field": reason. Deliberate exceptions only.
ADMIN = "an admin form: the Django admin gives model date fields its own date widget"
ALLOWED = {
    "trips.DayAdminForm.date": ADMIN,
    "trips.LodgingAdminForm.check_in": ADMIN,
    "trips.LodgingAdminForm.check_out": ADMIN,
    "trips.TransportLegAdminForm.date": ADMIN,
}


def kind_of(field):
    if isinstance(field, forms.DateTimeField) or type(field).__name__ == "LocalDateTimeField":
        return "datetime"
    if isinstance(field, forms.DateField):
        return "date"
    if isinstance(field, forms.TimeField):
        return "time"
    return None


def form_classes():
    for path in sorted(Path(settings.BASE_DIR, "apps").glob("*/forms.py")):
        module = importlib.import_module(f"apps.{path.parent.name}.forms")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, forms.BaseForm) and cls.__module__ == module.__name__:
                yield f"{path.parent.name}.{name}", cls


def fields_of(cls):
    try:
        return cls().fields
    except Exception:  # needs arguments (a trip, a user): its declared and model fields still count
        return cls.base_fields


class DatePickerTests(TestCase):
    def test_every_date_and_time_field_uses_a_picker(self):
        wrong, checked = [], 0
        for name, cls in form_classes():
            for field_name, field in fields_of(cls).items():
                kind = kind_of(field)
                where = f"{name}.{field_name}"
                if not kind or where in ALLOWED:
                    continue
                checked += 1
                widget_class, input_type, value_format = PICKERS[kind]
                widget = field.widget
                if not (isinstance(widget, widget_class) and widget.input_type == input_type
                        and widget.format == value_format):
                    wrong.append(f"{where}: {type(widget).__name__} (want widgets.{widget_class.__name__})")
        self.assertEqual(wrong, [], "\n".join(wrong))
        self.assertGreaterEqual(checked, 20)

    def test_widgets_render_the_browser_formats(self):
        from datetime import date, datetime, time
        self.assertIn('type="date"', widgets.DateInput().render("d", date(2027, 9, 18)))
        self.assertIn('value="2027-09-18"', widgets.DateInput().render("d", date(2027, 9, 18)))
        self.assertIn('value="20:05"', widgets.TimeInput().render("t", time(20, 5, 30)))
        html = widgets.DateTimeLocalInput().render("dt", datetime(2027, 9, 18, 20, 5))
        self.assertIn('type="datetime-local"', html)
        self.assertIn('value="2027-09-18T20:05"', html)
        self.assertIn('class="sbl-input"', html)
        self.assertNotIn("class=", widgets.DateInput(styled=False).render("d", None))
