# ============================================
# rewards/admin.py
# ============================================
from django.contrib import admin
from django.utils.html import format_html
from .models import RewardsProgram, RewardsProgramType


@admin.register(RewardsProgram)
class RewardsProgramAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'company',
        'program_type',
        'is_active',
        'display_order',
        'created_at',
    )
    
    list_filter = (
        'program_type',
        'is_active',
    )
    
    search_fields = (
        'name',
        'company',
        'description',
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Program Information', {
            'fields': (
                'name',
                'company',
                'program_type',
                'description',
                'website',
                'logo',
            )
        }),
        ('Tier Configuration', {
            'fields': ('tier_names',),
            'description': 'Enter tier names as JSON list, e.g., ["Silver", "Gold", "Platinum"]'
        }),
        ('Display Settings', {
            'fields': (
                'is_active',
                'display_order',
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_programs', 'deactivate_programs']
    
    def activate_programs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} program(s) activated.')
    activate_programs.short_description = 'Activate selected programs'
    
    def deactivate_programs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} program(s) deactivated.')
    deactivate_programs.short_description = 'Deactivate selected programs'
