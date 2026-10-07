# ============================================================================
# METRIC TO IMPERIAL CONVERSIONS
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP

def km_to_miles(km):
    """
    Convert kilometers to miles
    
    Args:
        km (float or Decimal): Distance in kilometers
    
    Returns:
        Decimal: Distance in miles, rounded to 2 decimal places
    
    Example:
        >>> km_to_miles(100)
        Decimal('62.14')
    """
    if km is None:
        return None
    km = Decimal(str(km))
    miles = km * Decimal('0.621371')
    return miles.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def miles_to_km(miles):
    """
    Convert miles to kilometers
    
    Args:
        miles (float or Decimal): Distance in miles
    
    Returns:
        Decimal: Distance in kilometers, rounded to 2 decimal places
    
    Example:
        >>> miles_to_km(100)
        Decimal('160.93')
    """
    if miles is None:
        return None
    miles = Decimal(str(miles))
    km = miles * Decimal('1.60934')
    return km.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def kg_to_lbs(kg):
    """
    Convert kilograms to pounds
    
    Args:
        kg (float or Decimal): Weight in kilograms
    
    Returns:
        Decimal: Weight in pounds, rounded to 2 decimal places
    
    Example:
        >>> kg_to_lbs(50)
        Decimal('110.23')
    """
    if kg is None:
        return None
    kg = Decimal(str(kg))
    lbs = kg * Decimal('2.20462')
    return lbs.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def lbs_to_kg(lbs):
    """
    Convert pounds to kilograms
    
    Args:
        lbs (float or Decimal): Weight in pounds
    
    Returns:
        Decimal: Weight in kilograms, rounded to 2 decimal places
    
    Example:
        >>> lbs_to_kg(100)
        Decimal('45.36')
    """
    if lbs is None:
        return None
    lbs = Decimal(str(lbs))
    kg = lbs * Decimal('0.453592')
    return kg.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def celsius_to_fahrenheit(celsius):
    """
    Convert Celsius to Fahrenheit
    
    Args:
        celsius (float or Decimal): Temperature in Celsius
    
    Returns:
        Decimal: Temperature in Fahrenheit, rounded to 1 decimal place
    
    Example:
        >>> celsius_to_fahrenheit(25)
        Decimal('77.0')
    """
    if celsius is None:
        return None
    celsius = Decimal(str(celsius))
    fahrenheit = (celsius * Decimal('9') / Decimal('5')) + Decimal('32')
    return fahrenheit.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def fahrenheit_to_celsius(fahrenheit):
    """
    Convert Fahrenheit to Celsius
    
    Args:
        fahrenheit (float or Decimal): Temperature in Fahrenheit
    
    Returns:
        Decimal: Temperature in Celsius, rounded to 1 decimal place
    
    Example:
        >>> fahrenheit_to_celsius(77)
        Decimal('25.0')
    """
    if fahrenheit is None:
        return None
    fahrenheit = Decimal(str(fahrenheit))
    celsius = (fahrenheit - Decimal('32')) * Decimal('5') / Decimal('9')
    return celsius.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def meters_to_feet(meters):
    """
    Convert meters to feet
    
    Args:
        meters (float or Decimal): Distance in meters
    
    Returns:
        Decimal: Distance in feet, rounded to 2 decimal places
    
    Example:
        >>> meters_to_feet(100)
        Decimal('328.08')
    """
    if meters is None:
        return None
    meters = Decimal(str(meters))
    feet = meters * Decimal('3.28084')
    return feet.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def feet_to_meters(feet):
    """
    Convert feet to meters
    
    Args:
        feet (float or Decimal): Distance in feet
    
    Returns:
        Decimal: Distance in meters, rounded to 2 decimal places
    
    Example:
        >>> feet_to_meters(328)
        Decimal('99.97')
    """
    if feet is None:
        return None
    feet = Decimal(str(feet))
    meters = feet * Decimal('0.3048')
    return meters.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def liters_to_gallons(liters):
    """
    Convert liters to US gallons
    
    Args:
        liters (float or Decimal): Volume in liters
    
    Returns:
        Decimal: Volume in US gallons, rounded to 2 decimal places
    
    Example:
        >>> liters_to_gallons(10)
        Decimal('2.64')
    """
    if liters is None:
        return None
    liters = Decimal(str(liters))
    gallons = liters * Decimal('0.264172')
    return gallons.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def gallons_to_liters(gallons):
    """
    Convert US gallons to liters
    
    Args:
        gallons (float or Decimal): Volume in US gallons
    
    Returns:
        Decimal: Volume in liters, rounded to 2 decimal places
    
    Example:
        >>> gallons_to_liters(2.64)
        Decimal('9.99')
    """
    if gallons is None:
        return None
    gallons = Decimal(str(gallons))
    liters = gallons * Decimal('3.78541')
    return liters.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
