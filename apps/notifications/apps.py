from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'apps.notifications'
    label = 'notifications'

    def ready(self):
        from . import receivers  # noqa: F401  (role request decisions)
