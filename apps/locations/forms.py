# locations/forms.py
"""Edit forms for regions, cities and places (the country edit page predates these and
reads the POST by hand). Approval, counters and featured flags stay in the admin."""
from django import forms

from apps.media_app.forms import PictureFormMixin

from .models import POI, City, Country, Region
from .widgets import CountryTaggedSelect

INPUT = {"class": "sbl-input"}


class _LocationForm(PictureFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "sbl-check")
            else:
                widget.attrs.setdefault("class", "sbl-input")
        if "description" in self.fields:
            self.fields["description"].widget.attrs.setdefault("rows", 4)
        self.setup_picture()


class RegionForm(_LocationForm):
    class Meta:
        model = Region
        fields = ["country", "name", "code", "latitude", "longitude", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["country"].queryset = Country.objects.order_by("name")


class CityForm(_LocationForm):
    class Meta:
        model = City
        fields = ["country", "region", "name", "latitude", "longitude", "timezone", "elevation_m", "population",
                  "capital_type", "best_time_to_visit", "average_daily_budget", "description"]
        widgets = {"region": CountryTaggedSelect}  # options follow the Country choice (country_filter.js)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["country"].queryset = Country.objects.order_by("name")
        self.fields["region"].queryset = Region.objects.order_by("name")

    def clean(self):
        cleaned = super().clean()
        country, region = cleaned.get("country"), cleaned.get("region")
        if country and region and region.country_id != country.pk:
            self.add_error("region", f"{region.name} is not in {country.name}.")
        return cleaned


class POIForm(_LocationForm):
    class Meta:
        model = POI
        fields = ["city", "name", "poi_type", "latitude", "longitude", "elevation_m", "address", "description",
                  "website", "phone", "entry_fee", "entry_fee_currency", "typical_duration",
                  "wheelchair_accessible", "parking_available"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].queryset = City.objects.select_related("region", "country").order_by("name")
        self.fields["city"].label_from_instance = lambda c: ", ".join(
            part for part in (c.name, c.region.code or c.region.name if c.region_id else "", c.country.name) if part)
