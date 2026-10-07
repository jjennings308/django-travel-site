# core/utils/__init__.py
"""
Core utility functions organized by category.

Usage:
    # Import specific functions
    from core.utils.slug import generate_unique_slug
    from core.utils.age import calculate_age
    from core.utils.imperial_metric import km_to_miles
    from core.utils.currency import convert_currency
    from core.utils.breadcrumbs import build_breadcrumbs, BreadcrumbPatterns
    from core.utils.helpers import convert_distance_by_preference
    
    # Or import commonly used functions directly from core.utils
    from core.utils import generate_unique_slug, calculate_age
"""

# Commonly used functions available directly from core.utils
from .slug import generate_unique_slug
from .age import calculate_age

# Make submodules easily importable
from . import imperial_metric
from . import currency
from . import breadcrumbs
from . import helpers

__all__ = [
    # Direct exports
    'generate_unique_slug',
    'calculate_age',
    
    # Submodules
    'imperial_metric',
    'currency',
    'breadcrumbs',
    'helpers',
]
