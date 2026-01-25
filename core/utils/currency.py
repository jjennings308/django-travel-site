# ============================================================================
# CURRENCY CONVERSIONS
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP
import requests
from django.core.cache import cache


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
