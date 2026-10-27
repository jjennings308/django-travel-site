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


class CitySearchInput(forms.Select):
    """A city picked by typing (day-first plan, P1): a type-to-search box over ``locations:city_search``
    (Alpine, ``locations/city_search.js``) that keeps the chosen id in a hidden input, shows the choices
    of the ``chips_group`` optgroup ("This trip") as chips before anything is typed, offers "Add “…” as
    a new city" (``locations:city_new``) when nothing matches, and gives the hidden input the city's
    ``data-tz`` (so the leg page can fill a blank zone, E5). Without JavaScript the box stays hidden
    (``x-cloak``) and the ordinary select of its choices, in a ``<noscript>``, does the job; the
    hidden input only gets its ``name`` from Alpine, so the two never both submit."""

    template_name = "locations/widgets/city_search.html"

    def __init__(self, attrs=None, choices=(), zones=None, chips_group="This trip", placeholder="Type a city…"):
        super().__init__(attrs, choices)
        self.zones = zones or {}
        self.chips_group = chips_group
        self.placeholder = placeholder

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        zone = self.zones.get(str(getattr(value, "value", value)))
        if zone:
            option["attrs"]["data-tz"] = zone
        return option

    def get_context(self, name, value, attrs):
        from django.urls import reverse
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        selected, chips = [], []
        for group_name, options, _index in widget["optgroups"]:
            for option in options:
                if not option["value"]:
                    continue
                city = {"id": str(option["value"]), "label": str(option["label"]),
                        "timezone": option["attrs"].get("data-tz", "")}
                if option["selected"]:
                    selected.append(city)
                if group_name == self.chips_group:
                    chips.append(city)
        element_id = widget["attrs"].get("id") or f"id_{name}"
        fallback = {**widget["attrs"], "id": f"{element_id}_fallback"}
        widget["search"] = {
            "fallback": {"attrs": fallback},
            "config_id": f"{element_id}_config",
            "text_class": widget["attrs"].get("class", ""),
            "placeholder": self.placeholder,
            "config": {
                "name": widget["name"], "multiple": self.allow_multiple_selected, "selected": selected,
                "chips": chips, "searchUrl": reverse("locations:city_search"),
                "newUrl": reverse("locations:city_new"), "countriesUrl": reverse("locations:country_options"),
                "regionsUrl": reverse("locations:get_regions", args=[0]),
            },
        }
        return context


class CitySearchMultiple(CitySearchInput, forms.SelectMultiple):
    """The same box for several cities (a trip's cities): chips with × for those chosen, typing adds."""

    def __init__(self, attrs=None, choices=(), zones=None, chips_group=None, placeholder="Type to add a city…"):
        super().__init__(attrs, choices, zones=zones, chips_group=chips_group, placeholder=placeholder)
