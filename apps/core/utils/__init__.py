"""
Core utility functions organized by category.

Usage:
    # Import specific functions
    from apps.core.utils.slug import generate_unique_slug
    from apps.core.utils.age import calculate_age
    from apps.core.utils.imperial_metric import km_to_miles
    from apps.core.utils.currency import convert_currency
    from apps.core.utils.breadcrumbs import build_breadcrumbs, BreadcrumbPatterns
    from apps.core.utils.helpers import convert_distance_by_preference

    # Or import commonly used functions directly from core.utils
    from apps.core.utils import generate_unique_slug, calculate_age
"""

# Commonly used functions available directly from core.utils
# Make submodules easily importable
from . import breadcrumbs, currency, helpers, imperial_metric
from .age import calculate_age
from .slug import generate_unique_slug

__all__ = [
    # Direct exports
    "generate_unique_slug",
    "calculate_age",
    # Submodules
    "imperial_metric",
    "currency",
    "breadcrumbs",
    "helpers",
]
