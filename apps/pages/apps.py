from django.apps import AppConfig


class PagesConfig(AppConfig):
    name = 'apps.pages'
    label = 'pages'

    def ready(self):
        from . import signals  # noqa: F401  (signing in cancels a pending account deletion, R13)
