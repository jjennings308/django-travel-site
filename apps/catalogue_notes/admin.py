from django.contrib import admin

from apps.approval_system.admin import ApprovableAdminMixin

from .models import CatalogueNote


@admin.register(CatalogueNote)
class CatalogueNoteAdmin(ApprovableAdminMixin, admin.ModelAdmin):
    list_display = ["__str__", "tone", "checked_on", "created_by"]
    list_filter = ["tone"]
    search_fields = ["text", "poi__name", "activity__name", "event__name"]
    raw_id_fields = ["poi", "activity", "event", "created_by"]
