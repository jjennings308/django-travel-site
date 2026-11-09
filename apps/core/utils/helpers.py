"""
Helper functions for user preferences and conversions
"""

from decimal import ROUND_HALF_UP, Decimal

from .imperial_metric import celsius_to_fahrenheit, km_to_miles, meters_to_feet


def convert_distance_by_preference(distance_km, user_preference="metric"):
    """
    Convert distance based on user's preference

    Args:
        distance_km (float or Decimal): Distance in kilometers
        user_preference (str): 'metric' or 'imperial'

    Returns:
        dict: Dictionary with value, unit, and formatted string

    Example:
        >>> convert_distance_by_preference(100, 'imperial')
        {'value': Decimal('62.14'), 'unit': 'mi', 'formatted': '62.14 mi'}
    """
    if distance_km is None:
        return None

    if user_preference == "imperial":
        value = km_to_miles(distance_km)
        unit = "mi"
    else:
        value = Decimal(str(distance_km)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        unit = "km"

    return {"value": value, "unit": unit, "formatted": f"{value} {unit}"}


def convert_elevation_by_preference(distance_m, user_preference="metric"):
    """
    Convert distance based on user's preference

    Args:
        distance_km (float or Decimal): Distance in kilometers
        user_preference (str): 'metric' or 'imperial'

    Returns:
        dict: Dictionary with value, unit, and formatted string

    Example:
        >>> convert_distance_by_preference(100, 'imperial')
        {'value': Decimal('62.14'), 'unit': 'mi', 'formatted': '62.14 mi'}
    """
    if distance_m is None:
        return None

    if user_preference == "imperial":
        value = meters_to_feet(distance_m)
        unit = "ft"
    else:
        value = Decimal(str(distance_m)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        unit = "m"

    return {"value": value, "unit": unit, "formatted": f"{value} {unit}"}


def convert_temperature_by_preference(temp_celsius, user_preference="metric"):
    """
    Convert temperature based on user's preference

    Args:
        temp_celsius (float or Decimal): Temperature in Celsius
        user_preference (str): 'metric' or 'imperial'

    Returns:
        dict: Dictionary with value, unit, and formatted string

    Example:
        >>> convert_temperature_by_preference(25, 'imperial')
        {'value': Decimal('77.0'), 'unit': '°F', 'formatted': '77.0°F'}
    """
    if temp_celsius is None:
        return None

    if user_preference == "imperial":
        value = celsius_to_fahrenheit(temp_celsius)
        unit = "°F"
    else:
        value = Decimal(str(temp_celsius)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        unit = "°C"

    return {"value": value, "unit": unit, "formatted": f"{value}{unit}"}
