# core/context_processors.py
from django.conf import settings


def site_branding(request):
    """Existing function - provides site branding information"""
    return {
        "SITE_NAME": getattr(settings, "SITE_NAME", ""),
        "SITE_TAGLINE": getattr(settings, "SITE_TAGLINE", ""),
    }


def user_settings(request):
    """
    Make user's AccountSettings available in all templates
    
    Provides:
        - user_units: 'metric' or 'imperial'
        - user_currency: 'USD', 'EUR', etc.
        - user_language: 'en', 'es', etc.
        - user_timezone: 'America/New_York', etc.
        - user_theme: 'brand', 'light', 'dark'
        - user_settings: Full AccountSettings object
    
    Usage in templates (after adding to TEMPLATES context_processors):
        {{ trip.distance_km|distance:user_units }}
        {{ trip.budget|currency:user_currency }}
    """
    defaults = {
        'user_units': 'metric',
        'user_currency': 'USD',
        'user_language': 'en',
        'user_timezone': 'UTC',
        'user_theme': 'brand',
    }
    
    if request.user.is_authenticated:
        try:
            user_settings_obj = request.user.settings
            return {
                'user_units': user_settings_obj.units,
                'user_currency': user_settings_obj.preferred_currency,
                'user_language': user_settings_obj.language,
                'user_timezone': user_settings_obj.timezone,
                'user_theme': user_settings_obj.theme,
                'user_settings': user_settings_obj,  # Full settings object
            }
        except Exception:
            # Settings don't exist or error occurred
            # Return defaults instead
            pass
    
    return defaults


def user_preferences(request):
    """
    Make user's TravelPreferences available in all templates
    
    Provides:
        - user_budget_pref: 'budget', 'moderate', 'luxury', 'mixed'
        - user_travel_styles: List of travel styles
        - user_travel_pace: 'slow', 'moderate', 'fast'
        - user_fitness_level: 1-5
        - user_travel_preferences: Full TravelPreferences object
    
    Usage in templates:
        {% if 'adventure' in user_travel_styles %}...{% endif %}
    """
    if request.user.is_authenticated:
        try:
            prefs = request.user.travel_preferences
            return {
                'user_budget_pref': prefs.budget_preference,
                'user_travel_styles': prefs.travel_styles,
                'user_travel_pace': prefs.travel_pace,
                'user_fitness_level': prefs.fitness_level,
                'user_travel_preferences': prefs,  # Full preferences object
            }
        except Exception:
            # Preferences don't exist
            pass
    
    return {
        'user_budget_pref': 'moderate',
        'user_travel_styles': [],
        'user_travel_pace': 'moderate',
        'user_fitness_level': 3,
    }
