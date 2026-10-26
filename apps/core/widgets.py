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


class CurrencySelect(forms.Widget):
    """A short list of currency codes (a trip's home currency first, then the local ones) plus
    **Other…**, which reveals a three-letter box (edit-by-day plan E4). Alpine hides the box until
    Other is picked; without JavaScript it simply shows. A stored code that isn't in the list is
    added to it and shown selected, never silently changed. Posts ``<name>`` (the pick) and
    ``<name>_other`` (the typed code, used when the pick is Other)."""

    template_name = "core/widgets/currency_select.html"
    OTHER = "__other"

    def __init__(self, codes=(), allow_blank=False, attrs=None, styled=True):
        super().__init__({**({"class": SITE_INPUT} if styled else {}), **(attrs or {})})
        self.codes = list(codes)
        self.allow_blank = allow_blank

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        current = (value or "").strip().upper()
        codes = list(dict.fromkeys(code.upper() for code in self.codes if code))
        if current and current not in codes:
            codes.append(current)
        context["widget"].update(codes=codes, current=current, allow_blank=self.allow_blank,
                                 other_value=self.OTHER, other_name=f"{name}_other")
        return context

    def value_from_datadict(self, data, files, name):
        # A typed code wins: without JavaScript the box shows, and someone may type in it without
        # picking Other first.
        typed = (data.get(f"{name}_other") or "").strip()
        pick = data.get(name, "")
        return typed if typed or pick == self.OTHER else pick

    def value_omitted_from_data(self, data, files, name):
        return name not in data and f"{name}_other" not in data
