#core/admin.Py
from django.contrib import admin

class BaseModelAdmin(admin.ModelAdmin):
    """
    Base admin configuration for models using core mixins
    """

    readonly_fields = ("created_at", "updated_at", "deleted_at", "published_at")

    list_filter = (
        "is_deleted",
        "is_published",
        "is_featured",
        "created_at",
    )

    ordering = ("-created_at",)

    def get_queryset(self, request):
        """
        Hide soft-deleted objects by default
        """
        qs = super().get_queryset(request)
        return qs.filter(is_deleted=False)
