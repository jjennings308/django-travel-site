from .base import *


try:
    import django_extensions  # noqa: F401
    INSTALLED_APPS += ["django_extensions"]
except ImportError:
    pass
