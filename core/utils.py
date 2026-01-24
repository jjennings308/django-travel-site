# core/utils.py
from django.utils.text import slugify
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
import requests
from django.core.cache import cache
from datetime import timedelta


def generate_unique_slug(model_class, title, instance_id=None):
    """Generate a unique slug for a model instance"""
    slug = slugify(title)
    unique_slug = slug
    num = 1
    
    while model_class.objects.filter(slug=unique_slug).exclude(id=instance_id).exists():
        unique_slug = f"{slug}-{num}"
        num += 1
    
    return unique_slug


def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = timezone.now().date()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


# ============================================================================
# METRIC TO IMPERIAL CONVERSIONS
# ============================================================================

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


# ============================================================================
# CURRENCY CONVERSIONS
# ============================================================================

def get_exchange_rates(base_currency='USD', cache_timeout=3600):
    """
    Get current exchange rates from an API with caching
    
    Args:
        base_currency (str): Base currency code (default: USD)
        cache_timeout (int): Cache timeout in seconds (default: 3600 = 1 hour)
    
    Returns:
        dict: Exchange rates dictionary or None if failed
    
    Note:
        Uses exchangerate-api.com free tier (1500 requests/month)
        You can replace with other services like:
        - fixer.io
        - openexchangerates.org
        - currencyapi.com
    """
    cache_key = f'exchange_rates_{base_currency}'
    
    # Try to get from cache first
    cached_rates = cache.get(cache_key)
    if cached_rates:
        return cached_rates
    
    try:
        # Free API - replace with your preferred service
        url = f'https://api.exchangerate-api.com/v4/latest/{base_currency}'
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        rates = data.get('rates', {})
        
        # Cache the results
        cache.set(cache_key, rates, cache_timeout)
        return rates
    
    except Exception as e:
        # Log the error in production
        print(f"Error fetching exchange rates: {e}")
        return None


def convert_currency(amount, from_currency, to_currency, exchange_rates=None):
    """
    Convert amount from one currency to another
    
    Args:
        amount (float or Decimal): Amount to convert
        from_currency (str): Source currency code (e.g., 'USD')
        to_currency (str): Target currency code (e.g., 'EUR')
        exchange_rates (dict): Optional pre-fetched exchange rates
    
    Returns:
        Decimal: Converted amount rounded to 2 decimal places, or None if conversion failed
    
    Example:
        >>> convert_currency(100, 'USD', 'EUR')
        Decimal('92.50')  # Example rate
    """
    if amount is None:
        return None
    
    amount = Decimal(str(amount))
    
    # If same currency, return original amount
    if from_currency == to_currency:
        return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    # Get exchange rates if not provided
    if exchange_rates is None:
        exchange_rates = get_exchange_rates(from_currency)
    
    if not exchange_rates or to_currency not in exchange_rates:
        return None
    
    # Convert
    rate = Decimal(str(exchange_rates[to_currency]))
    converted = amount * rate
    
    return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def format_currency(amount, currency_code='USD'):
    """
    Format amount with currency symbol
    
    Args:
        amount (float or Decimal): Amount to format
        currency_code (str): Currency code (default: USD)
    
    Returns:
        str: Formatted currency string
    
    Example:
        >>> format_currency(1234.56, 'USD')
        '$1,234.56'
        >>> format_currency(1234.56, 'EUR')
        '€1,234.56'
    """
    if amount is None:
        return None
    
    amount = Decimal(str(amount))
    
    # Currency symbols mapping
    currency_symbols = {
        'USD': '$',
        'EUR': '€',
        'GBP': '£',
        'JPY': '¥',
        'AUD': 'A$',
        'CAD': 'C$',
        'CHF': 'Fr',
        'CNY': '¥',
        'INR': '₹',
        'MXN': 'Mex$',
        'BRL': 'R$',
        'ZAR': 'R',
        'KRW': '₩',
        'SGD': 'S$',
        'NZD': 'NZ$',
        'THB': '฿',
    }
    
    symbol = currency_symbols.get(currency_code, currency_code + ' ')
    
    # Format with thousand separators
    formatted_amount = f"{amount:,.2f}"
    
    # For some currencies that use symbol after amount
    suffix_currencies = ['EUR']
    if currency_code in suffix_currencies:
        return f"{formatted_amount}{symbol}"
    
    return f"{symbol}{formatted_amount}"


def get_common_currency_rates(base_currency='USD'):
    """
    Get exchange rates for most common travel currencies
    
    Args:
        base_currency (str): Base currency code (default: USD)
    
    Returns:
        dict: Dictionary of common currency codes and their exchange rates
    
    Example:
        >>> get_common_currency_rates('USD')
        {'EUR': Decimal('0.92'), 'GBP': Decimal('0.79'), ...}
    """
    common_currencies = [
        'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY', 
        'INR', 'MXN', 'BRL', 'ZAR', 'KRW', 'SGD', 'NZD', 'THB'
    ]
    
    all_rates = get_exchange_rates(base_currency)
    
    if not all_rates:
        return {}
    
    common_rates = {}
    for currency in common_currencies:
        if currency in all_rates:
            common_rates[currency] = Decimal(str(all_rates[currency])).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP
            )
    
    return common_rates


# ============================================================================
# HELPER FUNCTIONS FOR USER PREFERENCES
# ============================================================================

def convert_distance_by_preference(distance_km, user_preference='metric'):
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
    
    if user_preference == 'imperial':
        value = km_to_miles(distance_km)
        unit = 'mi'
    else:
        value = Decimal(str(distance_km)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        unit = 'km'
    
    return {
        'value': value,
        'unit': unit,
        'formatted': f"{value} {unit}"
    }


def convert_temperature_by_preference(temp_celsius, user_preference='metric'):
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
    
    if user_preference == 'imperial':
        value = celsius_to_fahrenheit(temp_celsius)
        unit = '°F'
    else:
        value = Decimal(str(temp_celsius)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        unit = '°C'
    
    return {
        'value': value,
        'unit': unit,
        'formatted': f"{value}{unit}"
    }
