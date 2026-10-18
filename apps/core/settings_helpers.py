"""Helpers that settings files import. Nothing here may import Django (settings aren't ready)."""
from email.utils import formataddr, getaddresses


def parse_admins(value):
    """``DJANGO_ADMINS`` ("James <j@example.com>, ops@example.com") -> ADMINS (a list of address
    strings, Django 6). Empty or unparsable -> [] (error emails off)."""
    return [formataddr((name, addr)) for name, addr in getaddresses([value or ""]) if "@" in addr]
