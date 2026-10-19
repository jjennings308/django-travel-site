# ============================================================================
# CURRENCY: codes, formatting, and conversion with the stored ECB rates (apps.core.rates)
# ============================================================================

from decimal import Decimal


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


def convert_currency(amount, from_currency, to_currency, on=None):
    """
    Convert ``amount`` between currencies with the stored ECB rates (``apps.core.rates``, site
    roadmap R10/R19): the rate on ``on`` (a date), else the latest. No live API calls.

    Returns:
        Decimal: the converted amount to the cent, or None for an unknown currency (never a guess).
    """
    from apps.core.rates import Rates

    if amount is None:
        return None
    conversion = Rates([from_currency, to_currency], [on] if on else ()).convert(amount, from_currency, to_currency, on)
    return conversion.amount if conversion else None


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
