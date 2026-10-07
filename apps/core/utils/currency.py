# ============================================================================
# CURRENCY CONVERSIONS
# ============================================================================

from decimal import Decimal, ROUND_HALF_UP
import requests
from django.core.cache import cache


# Active ISO 4217 currency codes (excludes funds, precious metals and test codes).
ISO_4217_CURRENCIES = {
    'AED': 'UAE Dirham', 'AFN': 'Afghan Afghani', 'ALL': 'Albanian Lek', 'AMD': 'Armenian Dram',
    'AOA': 'Angolan Kwanza', 'ARS': 'Argentine Peso', 'AUD': 'Australian Dollar', 'AWG': 'Aruban Florin',
    'AZN': 'Azerbaijani Manat', 'BAM': 'Bosnia-Herzegovina Convertible Mark', 'BBD': 'Barbadian Dollar',
    'BDT': 'Bangladeshi Taka', 'BGN': 'Bulgarian Lev', 'BHD': 'Bahraini Dinar', 'BIF': 'Burundian Franc',
    'BMD': 'Bermudian Dollar', 'BND': 'Brunei Dollar', 'BOB': 'Bolivian Boliviano', 'BRL': 'Brazilian Real',
    'BSD': 'Bahamian Dollar', 'BTN': 'Bhutanese Ngultrum', 'BWP': 'Botswana Pula', 'BYN': 'Belarusian Ruble',
    'BZD': 'Belize Dollar', 'CAD': 'Canadian Dollar', 'CDF': 'Congolese Franc', 'CHF': 'Swiss Franc',
    'CLP': 'Chilean Peso', 'CNY': 'Chinese Yuan', 'COP': 'Colombian Peso', 'CRC': 'Costa Rican Colón',
    'CUP': 'Cuban Peso', 'CVE': 'Cape Verdean Escudo', 'CZK': 'Czech Koruna', 'DJF': 'Djiboutian Franc',
    'DKK': 'Danish Krone', 'DOP': 'Dominican Peso', 'DZD': 'Algerian Dinar', 'EGP': 'Egyptian Pound',
    'ERN': 'Eritrean Nakfa', 'ETB': 'Ethiopian Birr', 'EUR': 'Euro', 'FJD': 'Fijian Dollar',
    'FKP': 'Falkland Islands Pound', 'GBP': 'British Pound', 'GEL': 'Georgian Lari', 'GHS': 'Ghanaian Cedi',
    'GIP': 'Gibraltar Pound', 'GMD': 'Gambian Dalasi', 'GNF': 'Guinean Franc', 'GTQ': 'Guatemalan Quetzal',
    'GYD': 'Guyanese Dollar', 'HKD': 'Hong Kong Dollar', 'HNL': 'Honduran Lempira', 'HTG': 'Haitian Gourde',
    'HUF': 'Hungarian Forint', 'IDR': 'Indonesian Rupiah', 'ILS': 'Israeli New Shekel', 'INR': 'Indian Rupee',
    'IQD': 'Iraqi Dinar', 'IRR': 'Iranian Rial', 'ISK': 'Icelandic Króna', 'JMD': 'Jamaican Dollar',
    'JOD': 'Jordanian Dinar', 'JPY': 'Japanese Yen', 'KES': 'Kenyan Shilling', 'KGS': 'Kyrgyzstani Som',
    'KHR': 'Cambodian Riel', 'KMF': 'Comorian Franc', 'KPW': 'North Korean Won', 'KRW': 'South Korean Won',
    'KWD': 'Kuwaiti Dinar', 'KYD': 'Cayman Islands Dollar', 'KZT': 'Kazakhstani Tenge', 'LAK': 'Lao Kip',
    'LBP': 'Lebanese Pound', 'LKR': 'Sri Lankan Rupee', 'LRD': 'Liberian Dollar', 'LSL': 'Lesotho Loti',
    'LYD': 'Libyan Dinar', 'MAD': 'Moroccan Dirham', 'MDL': 'Moldovan Leu', 'MGA': 'Malagasy Ariary',
    'MKD': 'Macedonian Denar', 'MMK': 'Myanmar Kyat', 'MNT': 'Mongolian Tögrög', 'MOP': 'Macanese Pataca',
    'MRU': 'Mauritanian Ouguiya', 'MUR': 'Mauritian Rupee', 'MVR': 'Maldivian Rufiyaa', 'MWK': 'Malawian Kwacha',
    'MXN': 'Mexican Peso', 'MYR': 'Malaysian Ringgit', 'MZN': 'Mozambican Metical', 'NAD': 'Namibian Dollar',
    'NGN': 'Nigerian Naira', 'NIO': 'Nicaraguan Córdoba', 'NOK': 'Norwegian Krone', 'NPR': 'Nepalese Rupee',
    'NZD': 'New Zealand Dollar', 'OMR': 'Omani Rial', 'PAB': 'Panamanian Balboa', 'PEN': 'Peruvian Sol',
    'PGK': 'Papua New Guinean Kina', 'PHP': 'Philippine Peso', 'PKR': 'Pakistani Rupee', 'PLN': 'Polish Złoty',
    'PYG': 'Paraguayan Guaraní', 'QAR': 'Qatari Riyal', 'RON': 'Romanian Leu', 'RSD': 'Serbian Dinar',
    'RUB': 'Russian Ruble', 'RWF': 'Rwandan Franc', 'SAR': 'Saudi Riyal', 'SBD': 'Solomon Islands Dollar',
    'SCR': 'Seychellois Rupee', 'SDG': 'Sudanese Pound', 'SEK': 'Swedish Krona', 'SGD': 'Singapore Dollar',
    'SHP': 'Saint Helena Pound', 'SLE': 'Sierra Leonean Leone', 'SOS': 'Somali Shilling',
    'SRD': 'Surinamese Dollar', 'SSP': 'South Sudanese Pound', 'STN': 'São Tomé and Príncipe Dobra',
    'SVC': 'Salvadoran Colón', 'SYP': 'Syrian Pound', 'SZL': 'Swazi Lilangeni', 'THB': 'Thai Baht',
    'TJS': 'Tajikistani Somoni', 'TMT': 'Turkmenistani Manat', 'TND': 'Tunisian Dinar', 'TOP': 'Tongan Paʻanga',
    'TRY': 'Turkish Lira', 'TTD': 'Trinidad and Tobago Dollar', 'TWD': 'New Taiwan Dollar',
    'TZS': 'Tanzanian Shilling', 'UAH': 'Ukrainian Hryvnia', 'UGX': 'Ugandan Shilling', 'USD': 'US Dollar',
    'UYU': 'Uruguayan Peso', 'UZS': 'Uzbekistani Som', 'VES': 'Venezuelan Bolívar', 'VND': 'Vietnamese Đồng',
    'VUV': 'Vanuatu Vatu', 'WST': 'Samoan Tālā', 'XAF': 'Central African CFA Franc',
    'XCD': 'East Caribbean Dollar', 'XCG': 'Caribbean Guilder', 'XOF': 'West African CFA Franc',
    'XPF': 'CFP Franc', 'YER': 'Yemeni Rial', 'ZAR': 'South African Rand', 'ZMW': 'Zambian Kwacha',
    'ZWG': 'Zimbabwe Gold',
}

CURRENCY_CHOICES = [(code, f"{code} - {name}") for code, name in sorted(ISO_4217_CURRENCIES.items())]


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
