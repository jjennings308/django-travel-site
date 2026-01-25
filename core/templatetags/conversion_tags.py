# core/templatetags/conversion_tags.py
"""
Template tags for unit conversions based on user preferences.

Usage in templates:
{% load conversion_tags %}

{{ distance_km|distance:user.settings.unit_system }}
{{ temp_celsius|temperature:user.settings.unit_system }}
"""

from django import template
from decimal import Decimal

# Updated imports for new utils structure
from core.utils.helpers import (
    convert_distance_by_preference,
    convert_temperature_by_preference
)
from core.utils.imperial_metric import (
    km_to_miles,
    miles_to_km,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    kg_to_lbs,
    lbs_to_kg,
    meters_to_feet,
    feet_to_meters
)
from core.utils.currency import (
    convert_currency,
    format_currency
)

register = template.Library()


@register.filter
def distance(km, unit_system='metric'):
    """
    Convert distance based on user's unit preference.
    
    Usage:
        {{ trip.distance|distance:user.settings.unit_system }}
        {{ 100|distance:'imperial' }}  # Returns "62.14 mi"
    """
    if km is None:
        return ''
    
    result = convert_distance_by_preference(km, unit_system)
    return result['formatted'] if result else ''


@register.filter
def temperature(celsius, unit_system='metric'):
    """
    Convert temperature based on user's unit preference.
    
    Usage:
        {{ weather.temp|temperature:user.settings.unit_system }}
        {{ 25|temperature:'imperial' }}  # Returns "77.0°F"
    """
    if celsius is None:
        return ''
    
    result = convert_temperature_by_preference(celsius, unit_system)
    return result['formatted'] if result else ''


@register.filter
def km_miles(km):
    """
    Convert kilometers to miles.
    
    Usage:
        {{ distance_km|km_miles }}
    """
    if km is None:
        return ''
    miles = km_to_miles(km)
    return f"{miles} mi" if miles else ''


@register.filter
def miles_km(miles):
    """
    Convert miles to kilometers.
    
    Usage:
        {{ distance_miles|miles_km }}
    """
    if miles is None:
        return ''
    km = miles_to_km(miles)
    return f"{km} km" if km else ''


@register.filter
def c_to_f(celsius):
    """
    Convert Celsius to Fahrenheit.
    
    Usage:
        {{ temp_c|c_to_f }}
    """
    if celsius is None:
        return ''
    f = celsius_to_fahrenheit(celsius)
    return f"{f}°F" if f else ''


@register.filter
def f_to_c(fahrenheit):
    """
    Convert Fahrenheit to Celsius.
    
    Usage:
        {{ temp_f|f_to_c }}
    """
    if fahrenheit is None:
        return ''
    c = fahrenheit_to_celsius(fahrenheit)
    return f"{c}°C" if c else ''


@register.filter
def kg_pounds(kg):
    """
    Convert kilograms to pounds.
    
    Usage:
        {{ weight_kg|kg_pounds }}
    """
    if kg is None:
        return ''
    lbs = kg_to_lbs(kg)
    return f"{lbs} lbs" if lbs else ''


@register.filter
def pounds_kg(lbs):
    """
    Convert pounds to kilograms.
    
    Usage:
        {{ weight_lbs|pounds_kg }}
    """
    if lbs is None:
        return ''
    kg = lbs_to_kg(lbs)
    return f"{kg} kg" if kg else ''


@register.filter
def m_to_ft(meters):
    """
    Convert meters to feet.
    
    Usage:
        {{ height_m|m_to_ft }}
    """
    if meters is None:
        return ''
    feet = meters_to_feet(meters)
    return f"{feet} ft" if feet else ''


@register.filter
def ft_to_m(feet):
    """
    Convert feet to meters.
    
    Usage:
        {{ height_ft|ft_to_m }}
    """
    if feet is None:
        return ''
    m = feet_to_meters(feet)
    return f"{m} m" if m else ''


@register.filter
def currency(amount, currency_code='USD'):
    """
    Format amount as currency.
    
    Usage:
        {{ price|currency:'USD' }}
        {{ price|currency:'EUR' }}
    """
    if amount is None:
        return ''
    return format_currency(amount, currency_code) or ''


@register.filter
def convert_curr(amount, conversion):
    """
    Convert currency from one to another.
    
    Usage:
        {{ price|convert_curr:'USD:EUR' }}
    """
    if amount is None or not conversion:
        return ''
    
    try:
        from_curr, to_curr = conversion.split(':')
        result = convert_currency(amount, from_curr.strip(), to_curr.strip())
        return format_currency(result, to_curr.strip()) if result else ''
    except (ValueError, AttributeError):
        return ''


@register.simple_tag
def distance_display(km, unit_system='metric'):
    """
    Display distance with proper formatting.
    
    Usage:
        {% distance_display trip.distance user.settings.unit_system %}
    """
    if km is None:
        return ''
    
    result = convert_distance_by_preference(km, unit_system)
    return result['formatted'] if result else ''


@register.simple_tag
def temp_display(celsius, unit_system='metric'):
    """
    Display temperature with proper formatting.
    
    Usage:
        {% temp_display weather.temp user.settings.unit_system %}
    """
    if celsius is None:
        return ''
    
    result = convert_temperature_by_preference(celsius, unit_system)
    return result['formatted'] if result else ''
