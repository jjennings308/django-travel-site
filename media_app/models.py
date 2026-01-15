# media/models.py
from django.db import models
from core.models import TimeStampedModel
from accounts.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from taggit.managers import TaggableManager

import os
import uuid
import mimetypes


def user_media_upload_path(instance, filename):
    """Generate upload path for user media"""
    # Upload to: media/users/{user_id}/{year}/{month}/{filename}
    from django.utils import timezone
    now = timezone.now()
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    return f"users/{instance.uploaded_by.id}/{now.year}/{now.month:02d}/{filename}"


def site_media_upload_path(instance, filename):
    """Generate upload path for site/admin media"""
    # Upload to: media/site/{content_type}/{year}/{month}/{filename}
    from django.utils import timezone
    now = timezone.now()
    content_type = instance.content_type.model if instance.content_type else 'general'
    return f"site/{content_type}/{now.year}/{now.month:02d}/{filename}"


class MediaCategory(TimeStampedModel):
    """Categories for organizing media"""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="E.g., Trip Photos, Reviews, Profile Pictures, Activity Images"
    )
    description = models.TextField(blank=True)
    is_system_category = models.BooleanField(
        default=False,
        help_text="System-reserved category"
    )
    
    class Meta:
        db_table = 'media_categories'
        verbose_name_plural = 'Media Categories'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Media(TimeStampedModel):
    """Media files (photos, videos, documents)"""
    
    # File information
    file = models.FileField(
        upload_to=user_media_upload_path,
        max_length=500
    )
    
    MEDIA_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('document', 'Document'),
        ('audio', 'Audio')
    ]
    media_type = models.CharField(
        max_length=20,
        choices=MEDIA_TYPES,
        blank=True,
        db_index=True
    )
    
    # Auto-detected from file
    file_size = models.BigIntegerField(
        help_text="File size in bytes",
        null=True,
        blank=True
    )
    mime_type = models.CharField(max_length=100, blank=True)
    file_extension = models.CharField(max_length=10, blank=True)
    
    # Image-specific fields
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    
    # Video-specific fields
    duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Video duration in seconds"
    )
    
    # Thumbnail for videos/documents
    thumbnail = models.ImageField(
        upload_to='thumbnails/%Y/%m/',
        null=True,
        blank=True
    )
    
    # Ownership and attribution
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='uploaded_media'
    )
    
    is_user_generated = models.BooleanField(
        default=True,
        help_text="True for user uploads, False for site/admin content"
    )
    
    # Generic relation to any model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Type of object this media is attached to"
    )
    object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ID of the object this media is attached to"
    )
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Categorization
    category = models.ForeignKey(
        MediaCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_files'
    )
    
    # Metadata
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional title for the media"
    )
    caption = models.TextField(
        blank=True,
        help_text="Caption or description"
    )
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="Alt text for accessibility"
    )
    
    # Location data (if available from EXIF or user input)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    location_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Named location where photo was taken"
    )
    
    # Date photo was taken (from EXIF or user input)
    taken_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When photo/video was taken"
    )
    
    # Tags
    tags =TaggableManager(blank=True)
    
    # Privacy and moderation
    PRIVACY_CHOICES = [
        ('public', 'Public'),
        ('friends', 'Friends Only'),
        ('private', 'Private')
    ]
    privacy = models.CharField(
        max_length=20,
        choices=PRIVACY_CHOICES,
        default='public'
    )
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Featured in galleries/homepage"
    )
    
    is_approved = models.BooleanField(
        default=True,
        help_text="Approved by moderators"
    )
    
    is_flagged = models.BooleanField(
        default=False,
        help_text="Flagged for review"
    )
    flagged_reason = models.TextField(blank=True)
    
    # Display order (for galleries)
    display_order = models.IntegerField(
        default=0,
        help_text="Order in galleries/albums"
    )
    
    # Stats
    view_count = models.IntegerField(default=0)
    download_count = models.IntegerField(default=0)
    like_count = models.IntegerField(default=0)
    
    # Storage
    storage_backend = models.CharField(
        max_length=50,
        default='local',
        help_text="Storage backend (local, s3, cloudinary, etc.)"
    )
    
    class Meta:
        db_table = 'media'
        verbose_name_plural = 'Media'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['uploaded_by', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['media_type', 'is_approved']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        filename = os.path.basename(self.file.name)
        return f"{filename} by {self.uploaded_by.username}"
    
    @property
    def file_size_mb(self):
        """Return file size in MB"""
        if self.file_size:
            return round(self.file_size / (1024 * 1024), 2)
        return None
    
    def is_attached(self):
        return self.content_type_id is not None and self.object_id is not None

    def attached_object_exists(self):
        if not self.is_attached():
            return False
        return self.content_object is not None

    def save(self, *args, **kwargs):
        # Auto-detect file properties
        if self.file:
            self.file_size = self.file.size
            self.file_extension = os.path.splitext(self.file.name)[1].lower().lstrip('.')

            mime, _ = mimetypes.guess_type(self.file.name)
            self.mime_type = mime or ''

            # Detect media type from extension if not set
            if not self.media_type:
                image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic']
                video_exts = ['mp4', 'mov', 'avi', 'mkv', 'webm']
                doc_exts = ['pdf', 'doc', 'docx', 'txt']

                if self.file_extension in image_exts:
                    self.media_type = 'image'
                elif self.file_extension in video_exts:
                    self.media_type = 'video'
                elif self.file_extension in doc_exts:
                    self.media_type = 'document'

        super().save(*args, **kwargs)


class MediaAlbum(TimeStampedModel):
    """Albums/collections of media"""
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='media_albums'
    )
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Privacy
    PRIVACY_CHOICES = [
        ('public', 'Public'),
        ('friends', 'Friends Only'),
        ('private', 'Private')
    ]
    privacy = models.CharField(
        max_length=20,
        choices=PRIVACY_CHOICES,
        default='public'
    )
    
    # Cover image
    cover_image = models.ForeignKey(
        Media,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cover_for_albums'
    )
    
    # Stats
    @property
    def media_count(self):
        return self.album_media_items.count()
    view_count = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'media_albums'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} by {self.user.username}"


class AlbumMedia(TimeStampedModel):
    """Many-to-many relationship between albums and media with order"""
    
    album = models.ForeignKey(
        MediaAlbum,
        on_delete=models.CASCADE,
        related_name='album_media_items'
    )
    media = models.ForeignKey(
        Media,
        on_delete=models.CASCADE,
        related_name='album_memberships'
    )
    
    display_order = models.IntegerField(default=0)
    caption = models.TextField(
        blank=True,
        help_text="Album-specific caption (overrides media caption)"
    )
    
    class Meta:
        db_table = 'album_media'
        unique_together = [['album', 'media']]
        ordering = ['album', 'display_order']
    
    def __str__(self):
        return f"{self.media} in {self.album.title}"