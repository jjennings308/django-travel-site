# locations/templatetags/location_tags.py
# UPDATED VERSION with flag-icons library support

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def country_flag(country):
    """
    Returns the flag emoji for a country.
    If country.flag_emoji is already set, returns it.
    Otherwise, converts ISO code to flag emoji.
    
    Usage in any template:
    {% load location_tags %}
    {{ country|country_flag }}
    """
    # If flag_emoji is already stored, use it
    if hasattr(country, 'flag_emoji') and country.flag_emoji:
        return country.flag_emoji
    
    # Otherwise, convert ISO code to flag emoji
    if hasattr(country, 'iso_code') and country.iso_code:
        iso_code = country.iso_code.upper()
        if len(iso_code) == 2:
            # Convert ISO code to flag emoji using Unicode regional indicator symbols
            # Each letter A-Z maps to 🇦-🇿 (U+1F1E6 to U+1F1FF)
            flag = ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in iso_code)
            return flag
    
    return ''


@register.filter
def country_flag_icon(country):
    """
    Returns CSS class for flag-icons library (https://flagicons.lipis.dev/)
    Works with all browsers/systems - returns crisp SVG flags
    
    Usage:
    {% load location_tags %}
    <span class="{{ country|country_flag_icon }}"></span>
    
    Requires flag-icons CSS in base.html:
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/lipis/flag-icons@7.2.3/css/flag-icons.min.css"/>
    """
    if hasattr(country, 'iso_code') and country.iso_code:
        iso_code = country.iso_code.lower()
        return f"fi fi-{iso_code}"
    return ""


@register.filter
def iso_to_flag(iso_code):
    """
    Converts a 2-letter ISO country code to a flag emoji.
    
    Usage in any template:
    {% load location_tags %}
    {{ "US"|iso_to_flag }}  → 🇺🇸
    {{ country.iso_code|iso_to_flag }}  → 🇫🇷
    """
    if not iso_code or len(iso_code) != 2:
        return ''
    
    iso_code = iso_code.upper()
    # Convert ISO code to flag emoji
    flag = ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in iso_code)
    return flag


@register.filter
def country_display(country, format='flag_name'):
    """
    Flexible display of country with various format options.
    
    Usage:
    {% load location_tags %}
    {{ country|country_display }}              → 🇺🇸 United States (default)
    {{ country|country_display:"flag_name" }}  → 🇺🇸 United States
    {{ country|country_display:"flag_only" }}  → 🇺🇸
    {{ country|country_display:"name_only" }}  → United States
    {{ country|country_display:"flag_code" }}  → 🇺🇸 US
    {{ country|country_display:"icon_name" }}  → <icon> United States (uses flag-icons)
    """
    flag = country_flag(country)
    name = country.name if hasattr(country, 'name') else str(country)
    code = country.iso_code if hasattr(country, 'iso_code') else ''
    
    formats = {
        'flag_name': f"{flag} {name}" if flag else name,
        'flag_only': flag,
        'name_only': name,
        'flag_code': f"{flag} {code}" if flag else code,
        'code_name': f"{code} - {name}" if code else name,
        'icon_name': mark_safe(f'<span class="{country_flag_icon(country)}"></span> {name}'),
    }
    
    return formats.get(format, formats['flag_name'])


@register.simple_tag
def country_badge(country, classes='badge bg-secondary', use_icon=False):
    """
    Renders a country as a styled badge with flag.
    
    Usage:
    {% load location_tags %}
    {% country_badge country %}
    {% country_badge country "badge bg-primary" %}
    {% country_badge country "badge bg-primary" use_icon=True %}
    """
    name = country.name if hasattr(country, 'name') else str(country)
    
    html = f'<span class="{classes}">'
    
    if use_icon:
        # Use flag-icons library (crisp SVG)
        icon_class = country_flag_icon(country)
        if icon_class:
            html += f'<span class="{icon_class}" style="margin-right: 0.25rem;"></span>'
    else:
        # Use Unicode emoji
        flag = country_flag(country)
        if flag:
            html += f'<span style="margin-right: 0.25rem;">{flag}</span>'
    
    html += f'{name}</span>'
    
    return mark_safe(html)


@register.inclusion_tag('locations/_country_list.html')
def country_list(countries, style='badges', use_icons=False):
    """
    Renders a list of countries with flags.
    
    Usage:
    {% load location_tags %}
    {% country_list trip.countries.all %}
    {% country_list trip.countries.all style="list" %}
    {% country_list trip.countries.all style="badges" use_icons=True %}
    
    Styles: badges, list, inline, grid, compact
    use_icons: True = use flag-icons library (SVG), False = Unicode emoji
    """
    return {
        'countries': countries,
        'style': style,
        'use_icons': use_icons,
    }


@register.filter
def continents_list(countries):
    """
    Returns unique continents from a list of countries.
    
    Usage:
    {% load location_tags %}
    {% for continent in trip.countries.all|continents_list %}
        {{ continent }}
    {% endfor %}
    """
    if not countries:
        return []
    
    continents = set()
    for country in countries:
        if hasattr(country, 'continent') and country.continent:
            continents.add(country.continent)
    
    return sorted(continents)


@register.simple_tag
def country_stats(countries):
    """
    Returns statistics about a collection of countries.
    
    Usage:
    {% load location_tags %}
    {% country_stats trip.countries.all as stats %}
    {{ stats.count }} countries across {{ stats.continents|length }} continents
    """
    if not countries:
        return {'count': 0, 'continents': [], 'countries_by_continent': {}}
    
    continents = {}
    for country in countries:
        continent = getattr(country, 'continent', 'Unknown')
        if continent not in continents:
            continents[continent] = []
        continents[continent].append(country)
    
    return {
        'count': len(list(countries)),
        'continents': sorted(continents.keys()),
        'countries_by_continent': continents
    }
