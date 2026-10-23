"""The browser's own date and time pickers, for every form on the site.

Each widget sets the input type, the value format the browser expects and, unless
``styled=False``, the site's input class. Trip forms pass ``styled=False``: the
``.trips-ui`` component layer styles inputs by their type instead.
``apps/core/tests/test_date_pickers.py`` checks every form uses one of these.
"""
from django import forms

SITE_INPUT = "sbl-input"


class _Picker:
    input_type = ""
    value_format = ""

    def __init__(self, attrs=None, format=None, styled=True):
        attrs = {**({"class": SITE_INPUT} if styled else {}), **(attrs or {})}
        super().__init__(attrs=attrs, format=format or self.value_format)


class DateInput(_Picker, forms.DateInput):
    """``<input type="date">``, value 2027-09-18."""
    input_type = "date"
    value_format = "%Y-%m-%d"


class TimeInput(_Picker, forms.TimeInput):
    """``<input type="time">``, value 20:00 (no seconds)."""
    input_type = "time"
    value_format = "%H:%M"


class DateTimeLocalInput(_Picker, forms.DateTimeInput):
    """``<input type="datetime-local">``, value 2027-09-18T20:00 (wall clock, no zone)."""
    input_type = "datetime-local"
    value_format = "%Y-%m-%dT%H:%M"
