# locations/widgets.py
from django import forms


class CountryTaggedSelect(forms.Select):
    """A <select> of regions or cities whose options carry data-country, so
    locations/country_filter.js can show only the options of the country chosen in
    another select. Pass the source select's id as ``country_source``."""

    def __init__(self, attrs=None, country_source="id_country", **kwargs):
        attrs = {"data-country-source": country_source, **(attrs or {})}
        super().__init__(attrs, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            option["attrs"]["data-country"] = value.instance.country_id
        return option
