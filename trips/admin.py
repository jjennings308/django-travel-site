# trips/admin.py
from django.contrib import admin
from django.db.models import Count, Sum, Q
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    Trip,
    TripCollaborator,
    TripDay,
    TripActivity,
    TripBooking,
    TripExpense
)


class TripCollaboratorInline(admin.TabularInline):
    model = TripCollaborator
    extra = 1
    fields = ['user', 'role', 'invitation_accepted', 'invited_by']
    autocomplete_fields = ['user', 'invited_by']


class TripDayInline(admin.TabularInline):
    model = TripDay
    extra = 0
    fields = ['date', 'day_number', 'city', 'title', 'estimated_cost', 'actual_cost']
    autocomplete_fields = ['city']
    readonly_fields = ['day_number']


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'user',
        'date_range_display',
        'status_display',
        'trip_type',
        'primary_destination',
        'duration_display',
        'budget_display',
        'privacy',
        'engagement_display',
        'created_at'
    ]
    list_filter = [
        'status',
        'trip_type',
        'privacy',
        'is_template',
        'allow_collaborators',
        'start_date',
        'created_at'
    ]
    search_fields = [
        'title',
        'description',
        'user__username',
        'user__email',
        'primary_destination__name'
    ]
    autocomplete_fields = ['user', 'primary_destination']
    filter_horizontal = ['countries']
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'start_date'
    ordering = ['-start_date']
    inlines = [TripCollaboratorInline, TripDayInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'user',
                'title',
                'slug',
                'description',
                'trip_type'
            )
        }),
        ('Dates', {
            'fields': (
                'start_date',
                'end_date'
            )
        }),
        ('Destinations', {
            'fields': (
                'primary_destination',
                'countries'
            )
        }),
        ('Status & Privacy', {
            'fields': (
                'status',
                'privacy',
                'is_template',
                'allow_collaborators'
            )
        }),
        ('Budget', {
            'fields': (
                'estimated_budget',
                'actual_cost',
                'currency'
            )
        }),
        ('Travelers', {
            'fields': ('traveler_count',)
        }),
        ('Planning', {
            'fields': (
                'packing_list',
                'pre_trip_checklist',
                'notes'
            ),
            'classes': ('collapse',)
        }),
        ('Post-Trip', {
            'fields': (
                'overall_rating',
                'trip_summary',
                'highlights'
            ),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': (
                'day_count',
                'city_count',
                'activity_count',
                'booking_count',
                'view_count',
                'like_count',
                'clone_count'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'day_count',
        'city_count',
        'activity_count',
        'booking_count',
        'view_count',
        'like_count',
        'clone_count'
    ]
    
    actions = [
        'mark_as_completed',
        'mark_as_cancelled',
        'make_public',
        'make_private',
        'mark_as_template'
    ]
    
    def date_range_display(self, obj):
        today = timezone.now().date()
        if obj.start_date > today:
            color = '#3B82F6'
            icon = '📅'
        elif obj.start_date <= today <= obj.end_date:
            color = '#10B981'
            icon = '✈️'
        else:
            color = '#6B7280'
            icon = '✓'
        
        return format_html(
            '<div style="color: {};">{} {} → {}</div>'
            '<div style="color: #9CA3AF; font-size: 11px;">{} days</div>',
            color,
            icon,
            obj.start_date.strftime('%b %d, %Y'),
            obj.end_date.strftime('%b %d, %Y'),
            obj.duration_days
        )
    date_range_display.short_description = 'Dates'
    date_range_display.admin_order_field = 'start_date'
    
    def status_display(self, obj):
        colors = {
            'idea': '#9CA3AF',
            'planning': '#3B82F6',
            'booked': '#8B5CF6',
            'in_progress': '#10B981',
            'completed': '#059669',
            'cancelled': '#EF4444'
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: 500; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display().upper()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def duration_display(self, obj):
        return format_html(
            '<span style="font-weight: 500;">{}</span> days',
            obj.duration_days
        )
    duration_display.short_description = 'Duration'
    
    def budget_display(self, obj):
        if obj.estimated_budget or obj.actual_cost:
            estimated = f"{obj.currency} {obj.estimated_budget:,.2f}" if obj.estimated_budget else '-'
            actual = f"{obj.currency} {obj.actual_cost:,.2f}" if obj.actual_cost else '-'
            
            variance_html = ''
            if obj.budget_vs_actual is not None:
                variance = obj.budget_vs_actual
                color = '#EF4444' if variance > 0 else '#10B981'
                symbol = '+' if variance > 0 else ''
                variance_html = f'<div style="color: {color}; font-size: 11px;">{symbol}{obj.currency} {variance:,.2f}</div>'
            
            return format_html(
                '<div><strong>Est:</strong> {}</div>'
                '<div><strong>Act:</strong> {}</div>'
                '{}',
                estimated,
                actual,
                variance_html
            )
        return format_html('<span style="color: #9CA3AF;">-</span>')
    budget_display.short_description = 'Budget'
    
    def engagement_display(self, obj):
        return format_html(
            '<div style="font-size: 11px;">'
            '👁️ {} | ❤️ {} | 📋 {}'
            '</div>',
            obj.view_count,
            obj.like_count,
            obj.clone_count
        )
    engagement_display.short_description = 'Engagement'
    
    def mark_as_completed(self, request, queryset):
        updated = queryset.update(status='completed')
        self.message_user(request, f'{updated} trip(s) marked as completed.')
    mark_as_completed.short_description = 'Mark as completed'
    
    def mark_as_cancelled(self, request, queryset):
        updated = queryset.update(status='cancelled')
        self.message_user(request, f'{updated} trip(s) marked as cancelled.')
    mark_as_cancelled.short_description = 'Mark as cancelled'
    
    def make_public(self, request, queryset):
        updated = queryset.update(privacy='public')
        self.message_user(request, f'{updated} trip(s) made public.')
    make_public.short_description = 'Make public'
    
    def make_private(self, request, queryset):
        updated = queryset.update(privacy='private')
        self.message_user(request, f'{updated} trip(s) made private.')
    make_private.short_description = 'Make private'
    
    def mark_as_template(self, request, queryset):
        updated = queryset.update(is_template=True, privacy='public')
        self.message_user(request, f'{updated} trip(s) marked as template.')
    mark_as_template.short_description = 'Mark as template'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('user', 'primary_destination')
        queryset = queryset.prefetch_related('countries')
        return queryset


@admin.register(TripCollaborator)
class TripCollaboratorAdmin(admin.ModelAdmin):
    list_display = [
        'trip',
        'user',
        'role_display',
        'invitation_status_display',
        'invited_by',
        'invitation_date'
    ]
    list_filter = [
        'role',
        'invitation_accepted',
        'invitation_date'
    ]
    search_fields = [
        'user__username',
        'trip__title',
        'invited_by__username'
    ]
    autocomplete_fields = ['trip', 'user', 'invited_by']
    date_hierarchy = 'invitation_date'
    ordering = ['-invitation_date']
    
    fieldsets = (
        ('Collaboration', {
            'fields': ('trip', 'user', 'role')
        }),
        ('Invitation', {
            'fields': (
                'invited_by',
                'invitation_accepted',
                'invitation_date',
                'accepted_date'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at', 'invitation_date']
    
    def role_display(self, obj):
        colors = {
            'viewer': '#6B7280',
            'editor': '#3B82F6',
            'co_owner': '#8B5CF6'
        }
        color = colors.get(obj.role, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 500;">{}</span>',
            color,
            obj.get_role_display()
        )
    role_display.short_description = 'Role'
    role_display.admin_order_field = 'role'
    
    def invitation_status_display(self, obj):
        if obj.invitation_accepted:
            return format_html(
                '<span style="color: #10B981; font-weight: 500;">✓ Accepted</span>'
            )
        return format_html(
            '<span style="color: #F59E0B; font-weight: 500;">⏳ Pending</span>'
        )
    invitation_status_display.short_description = 'Status'
    invitation_status_display.admin_order_field = 'invitation_accepted'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('trip', 'user', 'invited_by')
        return queryset


@admin.register(TripDay)
class TripDayAdmin(admin.ModelAdmin):
    list_display = [
        'trip',
        'day_number',
        'date',
        'city',
        'title',
        'cost_display',
        'activity_count_display'
    ]
    list_filter = [
        'date',
        'trip__status'
    ]
    search_fields = [
        'trip__title',
        'title',
        'notes',
        'city__name'
    ]
    autocomplete_fields = ['trip', 'city', 'accommodation']
    date_hierarchy = 'date'
    ordering = ['trip', 'date']
    
    fieldsets = (
        ('Trip Day', {
            'fields': ('trip', 'date', 'day_number', 'city', 'title')
        }),
        ('Accommodation', {
            'fields': ('accommodation',)
        }),
        ('Budget', {
            'fields': ('estimated_cost', 'actual_cost')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Weather', {
            'fields': ('weather_forecast',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def cost_display(self, obj):
        if obj.estimated_cost or obj.actual_cost:
            estimated = f"${obj.estimated_cost:,.2f}" if obj.estimated_cost else '-'
            actual = f"${obj.actual_cost:,.2f}" if obj.actual_cost else '-'
            return format_html(
                '<div><small>Est:</small> {}</div>'
                '<div><small>Act:</small> {}</div>',
                estimated,
                actual
            )
        return format_html('<span style="color: #9CA3AF;">-</span>')
    cost_display.short_description = 'Cost'
    
    def activity_count_display(self, obj):
        count = obj.activities.count()
        return format_html(
            '<span style="font-weight: 500;">{}</span> activities',
            count
        )
    activity_count_display.short_description = 'Activities'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('trip', 'city', 'accommodation')
        return queryset


@admin.register(TripActivity)
class TripActivityAdmin(admin.ModelAdmin):
    list_display = [
        'title_display',
        'trip_day',
        'time_display',
        'booking_status_display',
        'cost_display',
        'is_confirmed',
        'is_completed',
        'rating_display'
    ]
    list_filter = [
        'booking_status',
        'is_confirmed',
        'is_completed',
        'trip_day__date'
    ]
    search_fields = [
        'custom_title',
        'custom_description',
        'trip_day__trip__title',
        'activity__name',
        'event__name',
        'vendor__name',
        'location_name'
    ]
    autocomplete_fields = ['trip_day', 'activity', 'event', 'vendor']
    ordering = ['trip_day', 'start_time', 'display_order']
    
    fieldsets = (
        ('Trip Day', {
            'fields': ('trip_day', 'display_order')
        }),
        ('Activity Reference', {
            'fields': (
                'activity',
                'event',
                'vendor',
                'custom_title',
                'custom_description'
            )
        }),
        ('Timing', {
            'fields': (
                'start_time',
                'end_time',
                'duration_minutes'
            )
        }),
        ('Location', {
            'fields': (
                'location_name',
                'address',
                'latitude',
                'longitude'
            ),
            'classes': ('collapse',)
        }),
        ('Booking', {
            'fields': (
                'booking_required',
                'booking_reference',
                'booking_status',
                'cost'
            )
        }),
        ('Status', {
            'fields': (
                'is_confirmed',
                'is_completed'
            )
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Post-Activity', {
            'fields': (
                'user_rating',
                'review_notes'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['mark_as_confirmed', 'mark_as_completed']
    
    def title_display(self, obj):
        return obj.title
    title_display.short_description = 'Activity'
    
    def time_display(self, obj):
        if obj.start_time:
            end = f" - {obj.end_time.strftime('%H:%M')}" if obj.end_time else ''
            duration = f" ({obj.duration_minutes}min)" if obj.duration_minutes else ''
            return format_html(
                '<span style="font-weight: 500;">{}{}</span>'
                '<span style="color: #6B7280; font-size: 11px;">{}</span>',
                obj.start_time.strftime('%H:%M'),
                end,
                duration
            )
        return format_html('<span style="color: #9CA3AF;">Not scheduled</span>')
    time_display.short_description = 'Time'
    
    def booking_status_display(self, obj):
        colors = {
            'none': '#9CA3AF',
            'needed': '#F59E0B',
            'pending': '#3B82F6',
            'confirmed': '#10B981',
            'cancelled': '#EF4444'
        }
        color = colors.get(obj.booking_status, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;">{}</span>',
            color,
            obj.get_booking_status_display()
        )
    booking_status_display.short_description = 'Booking'
    booking_status_display.admin_order_field = 'booking_status'
    
    def cost_display(self, obj):
        if obj.cost:
            return format_html('<span style="font-weight: 500;">${:,.2f}</span>', obj.cost)
        return format_html('<span style="color: #9CA3AF;">-</span>')
    cost_display.short_description = 'Cost'
    
    def rating_display(self, obj):
        if obj.user_rating:
            stars = '⭐' * obj.user_rating
            return format_html('<span title="{}/5">{}</span>', obj.user_rating, stars)
        return format_html('<span style="color: #9CA3AF;">-</span>')
    rating_display.short_description = 'Rating'
    
    def mark_as_confirmed(self, request, queryset):
        updated = queryset.update(is_confirmed=True, booking_status='confirmed')
        self.message_user(request, f'{updated} activity(ies) marked as confirmed.')
    mark_as_confirmed.short_description = 'Mark as confirmed'
    
    def mark_as_completed(self, request, queryset):
        updated = queryset.update(is_completed=True)
        self.message_user(request, f'{updated} activity(ies) marked as completed.')
    mark_as_completed.short_description = 'Mark as completed'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related(
            'trip_day__trip',
            'activity',
            'event',
            'vendor'
        )
        return queryset


@admin.register(TripBooking)
class TripBookingAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'trip',
        'booking_type_display',
        'date_display',
        'cost_display',
        'payment_status_display',
        'status_display',
        'confirmation_number'
    ]
    list_filter = [
        'booking_type',
        'status',
        'payment_status',
        'is_refundable',
        'start_date'
    ]
    search_fields = [
        'title',
        'description',
        'trip__title',
        'confirmation_number',
        'vendor__name'
    ]
    autocomplete_fields = ['trip', 'vendor']
    date_hierarchy = 'start_date'
    ordering = ['trip', 'start_date']
    
    fieldsets = (
        ('Trip', {
            'fields': ('trip',)
        }),
        ('Booking Details', {
            'fields': (
                'booking_type',
                'vendor',
                'title',
                'description'
            )
        }),
        ('Dates & Time', {
            'fields': (
                'start_date',
                'end_date',
                'start_time'
            )
        }),
        ('Confirmation', {
            'fields': (
                'confirmation_number',
                'booking_url'
            )
        }),
        ('Cost & Payment', {
            'fields': (
                'cost',
                'currency',
                'payment_status'
            )
        }),
        ('Status', {
            'fields': ('status',)
        }),
        ('Cancellation', {
            'fields': (
                'cancellation_policy',
                'is_refundable',
                'cancellation_deadline'
            ),
            'classes': ('collapse',)
        }),
        ('Contact', {
            'fields': (
                'contact_name',
                'contact_phone',
                'contact_email'
            ),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': (
                'notes',
                'attachment_urls'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    actions = ['mark_as_confirmed', 'mark_as_paid', 'mark_as_cancelled']
    
    def booking_type_display(self, obj):
        colors = {
            'flight': '#3B82F6',
            'accommodation': '#8B5CF6',
            'car_rental': '#F59E0B',
            'train': '#10B981',
            'bus': '#14B8A6',
            'tour': '#EC4899',
            'restaurant': '#EF4444',
            'event': '#F97316',
            'other': '#6B7280'
        }
        icons = {
            'flight': '✈️',
            'accommodation': '🏨',
            'car_rental': '🚗',
            'train': '🚆',
            'bus': '🚌',
            'tour': '🎯',
            'restaurant': '🍽️',
            'event': '🎫',
            'other': '📋'
        }
        color = colors.get(obj.booking_type, '#6B7280')
        icon = icons.get(obj.booking_type, '')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 500;">{} {}</span>',
            color,
            icon,
            obj.get_booking_type_display()
        )
    booking_type_display.short_description = 'Type'
    booking_type_display.admin_order_field = 'booking_type'
    
    def date_display(self, obj):
        if obj.end_date:
            return format_html(
                '{} → {}',
                obj.start_date.strftime('%b %d'),
                obj.end_date.strftime('%b %d, %Y')
            )
        time = f" {obj.start_time.strftime('%H:%M')}" if obj.start_time else ''
        return format_html('{}{}', obj.start_date.strftime('%b %d, %Y'), time)
    date_display.short_description = 'Date'
    date_display.admin_order_field = 'start_date'
    
    def cost_display(self, obj):
        return format_html(
            '<span style="font-weight: 500;">{} {:,.2f}</span>',
            obj.currency,
            obj.cost
        )
    cost_display.short_description = 'Cost'
    cost_display.admin_order_field = 'cost'
    
    def payment_status_display(self, obj):
        colors = {
            'unpaid': '#EF4444',
            'deposit': '#F59E0B',
            'paid': '#10B981',
            'refunded': '#6B7280'
        }
        color = colors.get(obj.payment_status, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;">{}</span>',
            color,
            obj.get_payment_status_display().upper()
        )
    payment_status_display.short_description = 'Payment'
    payment_status_display.admin_order_field = 'payment_status'
    
    def status_display(self, obj):
        colors = {
            'pending': '#F59E0B',
            'confirmed': '#10B981',
            'cancelled': '#EF4444',
            'completed': '#6B7280'
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;">{}</span>',
            color,
            obj.get_status_display().upper()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def mark_as_confirmed(self, request, queryset):
        updated = queryset.update(status='confirmed')
        self.message_user(request, f'{updated} booking(s) marked as confirmed.')
    mark_as_confirmed.short_description = 'Mark as confirmed'
    
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(payment_status='paid')
        self.message_user(request, f'{updated} booking(s) marked as paid.')
    mark_as_paid.short_description = 'Mark as paid'
    
    def mark_as_cancelled(self, request, queryset):
        updated = queryset.update(status='cancelled')
        self.message_user(request, f'{updated} booking(s) marked as cancelled.')
    mark_as_cancelled.short_description = 'Mark as cancelled'
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('trip', 'vendor')
        return queryset


@admin.register(TripExpense)
class TripExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'description',
        'trip',
        'trip_day',
        'category_display',
        'amount_display',
        'date',
        'payment_method',
        'has_receipt'
    ]
    list_filter = [
        'category',
        'date',
        'currency'
    ]
    search_fields = [
        'description',
        'notes',
        'trip__title',
        'payment_method'
    ]
    autocomplete_fields = ['trip', 'trip_day']
    date_hierarchy = 'date'
    ordering = ['trip', 'date']
    
    fieldsets = (
        ('Trip', {
            'fields': ('trip', 'trip_day')
        }),
        ('Expense Details', {
            'fields': (
                'category',
                'description',
                'amount',
                'currency',
                'date'
            )
        }),
        ('Payment', {
            'fields': ('payment_method',)
        }),
        ('Receipt', {
            'fields': ('receipt_photo',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def category_display(self, obj):
        colors = {
            'accommodation': '#8B5CF6',
            'food': '#EF4444',
            'transportation': '#3B82F6',
            'activities': '#10B981',
            'shopping': '#EC4899',
            'entertainment': '#F59E0B',
            'miscellaneous': '#6B7280'
        }
        color = colors.get(obj.category, '#6B7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;">{}</span>',
            color,
            obj.get_category_display()
        )
    category_display.short_description = 'Category'
    category_display.admin_order_field = 'category'
    
    def amount_display(self, obj):
        return format_html(
            '<span style="font-weight: 500; font-size: 13px;">{} {:,.2f}</span>',
            obj.currency,
            obj.amount
        )
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'
    
    def has_receipt(self, obj):
        if obj.receipt_photo:
            return format_html('<span style="color: #10B981;">✓</span>')
        return format_html('<span style="color: #9CA3AF;">-</span>')
    has_receipt.short_description = 'Receipt'
    has_receipt.boolean = True
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.select_related('trip', 'trip_day')
        return queryset