# core/templatetags/conversion_tags.py
"""
Custom template tags for unit and currency conversions
Works with AccountSettings model (user.settings.units and user.settings.preferred_currency)

Usage in templates:
    {% load conversion_tags %}
    
    {{ trip.distance_km|distance:user.settings.units }}
    {{ city.temperature|temperature:user.settings.units }}
    {{ trip.budget|currency:user.settings.preferred_currency }}
"""

from django import template
from decimal import Decimal
from core.utils import (
    convert_distance_by_preference,
    convert_temperature_by_preference,
    format_currency,
    convert_currency,
    km_to_miles,
    miles_to_km,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
)

register = template.Library()


@register.filter
def distance(km, units='metric'):
    """
    Convert kilometers to preferred unit
    
    Usage:
        {{ trip.distance_km|distance:user.settings.units }}
        {{ 100|distance:"imperial" }}
    """
    if km is None:
        return ''
    
    result = convert_distance_by_preference(km, units)
    return result['formatted'] if result else ''


@register.filter
def temperature(celsius, units='metric'):
    """
    Convert Celsius to preferred unit
    
    Usage:
        {{ city.temperature|temperature:user.settings.units }}
        {{ 25|temperature:"imperial" }}
    """
    if celsius is None:
        return ''
    
    result = convert_temperature_by_preference(celsius, units)
    return result['formatted'] if result else ''


@register.filter
def currency(amount, currency_code='USD'):
    """
    Format amount as currency
    
    Usage:
        {{ trip.budget|currency:user.settings.preferred_currency }}
        {{ 1234.56|currency:"EUR" }}
    """
    if amount is None:
        return ''
    
    return format_currency(amount, currency_code)


@register.simple_tag
def convert_price(amount, from_currency, to_currency):
    """
    Convert and format price from one currency to another
    
    Usage:
        {% convert_price trip.budget_usd "USD" user.settings.preferred_currency %}
    """
    if amount is None:
        return ''
    
    converted = convert_currency(amount, from_currency, to_currency)
    if converted is None:
        return format_currency(amount, from_currency)  # Fallback to original
    
    return format_currency(converted, to_currency)


@register.filter
def miles(km):
    """
    Simple km to miles conversion
    
    Usage:
        {{ trip.distance_km|miles }}
    """
    if km is None:
        return ''
    
    result = km_to_miles(km)
    return f"{result} mi" if result else ''


@register.filter
def kilometers(miles_value):
    """
    Simple miles to km conversion
    
    Usage:
        {{ distance_miles|kilometers }}
    """
    if miles_value is None:
        return ''
    
    result = miles_to_km(miles_value)
    return f"{result} km" if result else ''


@register.filter
def fahrenheit(celsius):
    """
    Simple Celsius to Fahrenheit conversion
    
    Usage:
        {{ temperature_c|fahrenheit }}
    """
    if celsius is None:
        return ''
    
    result = celsius_to_fahrenheit(celsius)
    return f"{result}°F" if result else ''


@register.filter
def celsius_temp(fahrenheit_value):
    """
    Simple Fahrenheit to Celsius conversion
    
    Usage:
        {{ temperature_f|celsius_temp }}
    """
    if fahrenheit_value is None:
        return ''
    
    result = fahrenheit_to_celsius(fahrenheit_value)
    return f"{result}°C" if result else ''


@register.simple_tag(takes_context=True)
def user_distance(context, km):
    """
    Convert distance based on logged-in user's settings
    Uses user.settings.units from AccountSettings model
    
    Usage:
        {% user_distance trip.distance_km %}
    """
    if km is None:
        return ''
    
    request = context.get('request')
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            # Access AccountSettings via user.settings
            units = request.user.settings.units
            result = convert_distance_by_preference(km, units)
            return result['formatted'] if result else ''
        except:
            # Fallback if settings don't exist
            pass
    
    # Default to metric
    return f"{km} km"


@register.simple_tag(takes_context=True)
def user_temperature(context, celsius):
    """
    Convert temperature based on logged-in user's settings
    Uses user.settings.units from AccountSettings model
    
    Usage:
        {% user_temperature city.temperature %}
    """
    if celsius is None:
        return ''
    
    request = context.get('request')
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            # Access AccountSettings via user.settings
            units = request.user.settings.units
            result = convert_temperature_by_preference(celsius, units)
            return result['formatted'] if result else ''
        except:
            # Fallback if settings don't exist
            pass
    
    # Default to Celsius
    return f"{celsius}°C"


@register.simple_tag(takes_context=True)
def user_currency(context, amount, base_currency='USD'):
    """
    Format amount in user's preferred currency with conversion
    Uses user.settings.preferred_currency from AccountSettings model
    
    Usage:
        {% user_currency trip.budget_usd %}
        {% user_currency trip.budget_eur "EUR" %}
    """
    if amount is None:
        return ''
    
    request = context.get('request')
    target_currency = base_currency  # Default to the base currency
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            # Get user's preferred currency from settings
            target_currency = request.user.settings.preferred_currency
        except:
            pass
    
    # Convert if different currency
    if base_currency != target_currency:
        converted = convert_currency(amount, base_currency, target_currency)
        if converted:
            return format_currency(converted, target_currency)
    
    # No conversion needed or conversion failed
    return format_currency(amount, base_currency)


@register.inclusion_tag('core/includes/conversion_widget.html')
def conversion_widget(label, value, unit_type, user_units='metric'):
    """
    Render a conversion widget showing both metric and imperial
    
    Usage:
        {% conversion_widget "Distance" trip.distance_km "distance" user.settings.units %}
    
    Args:
        label: Display label (e.g., "Distance", "Temperature")
        value: The value to convert
        unit_type: Type of conversion ('distance' or 'temperature')
        user_units: User's preferred units from user.settings.units ('metric' or 'imperial')
    """
    if value is None:
        return {'show': False}
    
    if unit_type == 'distance':
        metric = f"{value} km"
        imperial_value = km_to_miles(value)
        imperial = f"{imperial_value} mi" if imperial_value else ''
        primary = metric if user_units == 'metric' else imperial
        secondary = imperial if user_units == 'metric' else metric
    
    elif unit_type == 'temperature':
        metric = f"{value}°C"
        imperial_value = celsius_to_fahrenheit(value)
        imperial = f"{imperial_value}°F" if imperial_value else ''
        primary = metric if user_units == 'metric' else imperial
        secondary = imperial if user_units == 'metric' else metric
    
    else:
        return {'show': False}
    
    return {
        'show': True,
        'label': label,
        'primary': primary,
        'secondary': secondary,
    }


@register.simple_tag(takes_context=True)
def auto_convert_distance(context, km):
    """
    Automatically convert distance and show both units if needed
    
    Usage:
        {% auto_convert_distance trip.distance_km %}
    Output: "100 km (62.14 mi)" or just "100 km" depending on user preference
    """
    if km is None:
        return ''
    
    request = context.get('request')
    units = 'metric'  # Default
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            units = request.user.settings.units
        except:
            pass
    
    if units == 'imperial':
        miles = km_to_miles(km)
        return f"{miles} mi ({km} km)" if miles else f"{km} km"
    else:
        miles = km_to_miles(km)
        return f"{km} km ({miles} mi)" if miles else f"{km} km"


@register.simple_tag(takes_context=True)
def auto_convert_temp(context, celsius):
    """
    Automatically convert temperature and show both units if needed
    
    Usage:
        {% auto_convert_temp city.temperature %}
    Output: "25°C (77°F)" or just "25°C" depending on user preference
    """
    if celsius is None:
        return ''
    
    request = context.get('request')
    units = 'metric'  # Default
    
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        try:
            units = request.user.settings.units
        except:
            pass
    
    if units == 'imperial':
        fahrenheit = celsius_to_fahrenheit(celsius)
        return f"{fahrenheit}°F ({celsius}°C)" if fahrenheit else f"{celsius}°C"
    else:
        fahrenheit = celsius_to_fahrenheit(celsius)
        return f"{celsius}°C ({fahrenheit}°F)" if fahrenheit else f"{celsius}°C"
