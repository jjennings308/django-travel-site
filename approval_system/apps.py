# approval_system/apps.py

from django.apps import AppConfig


class ApprovalSystemConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'approval_system'
    verbose_name = 'Approval System'
    
    def ready(self):
        # Import signals if any
        # import approval_system.signals
        pass
