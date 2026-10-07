# media/admin.py
from django.contrib import admin
from .models import MediaCategory, Media, MediaAlbum, AlbumMedia
from django.utils.html import format_html

@admin.register(MediaCategory)
class MediaCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_system_category', 'created_at']
    list_filter = ['is_system_category']
    search_fields = ['name', 'description']


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ['id', 'preview', 'get_filename', 'media_type', 'uploaded_by', 'privacy', 'is_approved', 'is_featured', 'created_at']
    list_filter = ['media_type', 'privacy', 'is_approved', 'is_flagged', 'is_featured', 'is_user_generated']
    search_fields = ['title', 'caption', 'uploaded_by__username', 'uploaded_by__email']
    readonly_fields = ['file_size', 'file_size_mb', 'mime_type', 'file_extension', 'width', 'height', 'duration', 'view_count', 'download_count', 'like_count', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('File Information', {
            'fields': ('file', 'media_type', 'thumbnail', 'file_size', 'file_size_mb', 'mime_type', 'file_extension')
        }),
        ('Metadata', {
            'fields': ('title', 'caption', 'alt_text', 'category', 'tags')
        }),
        ('Ownership', {
            'fields': ('uploaded_by', 'is_user_generated')
        }),
        ('Content Relationship', {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        ('Location & Time', {
            'fields': ('latitude', 'longitude', 'location_name', 'taken_at'),
            'classes': ('collapse',)
        }),
        ('Media Details', {
            'fields': ('width', 'height', 'duration'),
            'classes': ('collapse',)
        }),
        ('Privacy & Status', {
            'fields': ('privacy', 'is_approved', 'is_featured', 'is_flagged', 'flagged_reason', 'display_order')
        }),
        ('Stats', {
            'fields': ('view_count', 'download_count', 'like_count'),
            'classes': ('collapse',)
        }),
        ('Technical', {
            'fields': ('storage_backend', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_filename(self, obj):
        """Display just the filename"""
        import os
        return os.path.basename(obj.file.name) if obj.file else ''
    get_filename.short_description = 'File'
    
    def file_size_mb(self, obj):
        """Display file size in MB"""
        return obj.file_size_mb
    file_size_mb.short_description = 'Size (MB)'
    
    actions = ['approve_media', 'flag_media', 'feature_media']
    
    def approve_media(self, request, queryset):
        """Approve selected media"""
        updated = queryset.update(is_approved=True, is_flagged=False)
        self.message_user(request, f'{updated} media item(s) approved.')
    approve_media.short_description = 'Approve selected media'
    
    def flag_media(self, request, queryset):
        """Flag selected media for review"""
        updated = queryset.update(is_flagged=True)
        self.message_user(request, f'{updated} media item(s) flagged.')
    flag_media.short_description = 'Flag selected media'
    
    def feature_media(self, request, queryset):
        """Feature selected media"""
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} media item(s) featured.')
    feature_media.short_description = 'Feature selected media'


    def preview(self, obj):
        if obj.media_type == 'image' and obj.file:
            return format_html('<img src="{}" style="max-height: 60px;" />', obj.file.url)
        return "-"
    preview.short_description = 'Preview'


class AlbumMediaInline(admin.TabularInline):
    """Inline for managing media within albums"""
    model = AlbumMedia
    extra = 1
    fields = ['media', 'display_order', 'caption']
    raw_id_fields = ['media']


@admin.register(MediaAlbum)
class MediaAlbumAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'privacy', 'media_count', 'view_count', 'created_at']
    list_filter = ['privacy', 'created_at']
    search_fields = ['title', 'description', 'user__username', 'user__email']
    readonly_fields = ['media_count', 'view_count', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    inlines = [AlbumMediaInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'title', 'description')
        }),
        ('Settings', {
            'fields': ('privacy', 'cover_image')
        }),
        ('Stats', {
            'fields': ('media_count', 'view_count', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AlbumMedia)
class AlbumMediaAdmin(admin.ModelAdmin):
    list_display = ['album', 'media', 'display_order', 'created_at']
    list_filter = ['album__user', 'created_at']
    search_fields = ['album__title', 'caption']
    ordering = ['album', 'display_order']