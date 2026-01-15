# ============================================
# rewards/admin.py
# ============================================
from django.contrib import admin
from django.utils.html import format_html
from .models import RewardsProgram, UserRewardsMembership, RewardsProgramType


@admin.register(RewardsProgram)
class RewardsProgramAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'company',
        'program_type',
        'member_count_display',
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
    
    readonly_fields = ('created_at', 'updated_at', 'member_count')
    
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
        ('Statistics', {
            'fields': ('member_count',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def member_count_display(self, obj):
        count = obj.member_count
        return format_html(
            '<strong>{}</strong> member{}',
            count,
            's' if count != 1 else ''
        )
    member_count_display.short_description = 'Members'
    
    actions = ['activate_programs', 'deactivate_programs']
    
    def activate_programs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} program(s) activated.')
    activate_programs.short_description = 'Activate selected programs'
    
    def deactivate_programs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} program(s) deactivated.')
    deactivate_programs.short_description = 'Deactivate selected programs'


@admin.register(UserRewardsMembership)
class UserRewardsMembershipAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'program',
        'member_number',
        'current_tier',
        'points_balance',
        'is_primary',
        'tier_expires',
        'created_at',
    )
    
    list_filter = (
        'program__program_type',
        'is_primary',
        'show_on_profile',
        'notify_on_expiration',
        'program',
    )
    
    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'program__name',
        'program__company',
        'member_number',
    )
    
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    raw_id_fields = ('user',)
    
    fieldsets = (
        ('Membership', {
            'fields': (
                'id',
                'user',
                'program',
            )
        }),
        ('Account Details', {
            'fields': (
                'member_number',
                'member_name',
                'username',
            )
        }),
        ('Status & Balance', {
            'fields': (
                'current_tier',
                'points_balance',
                'tier_expires',
            )
        }),
        ('Preferences', {
            'fields': (
                'is_primary',
                'show_on_profile',
                'display_order',
            )
        }),
        ('Notifications', {
            'fields': (
                'notify_on_expiration',
                'expiration_notice_days',
            )
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_primary', 'show_on_profile_action', 'hide_from_profile_action']
    
    def mark_as_primary(self, request, queryset):
        for membership in queryset:
            membership.is_primary = True
            membership.save()  # Uses custom save logic
        self.message_user(request, f'{queryset.count()} membership(s) marked as primary.')
    mark_as_primary.short_description = 'Mark as primary program'
    
    def show_on_profile_action(self, request, queryset):
        updated = queryset.update(show_on_profile=True)
        self.message_user(request, f'{updated} membership(s) will show on profile.')
    show_on_profile_action.short_description = 'Show on profile'
    
    def hide_from_profile_action(self, request, queryset):
        updated = queryset.update(show_on_profile=False)
        self.message_user(request, f'{updated} membership(s) hidden from profile.')
    hide_from_profile_action.short_description = 'Hide from profile'