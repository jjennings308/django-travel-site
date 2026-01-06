# core/models.py
from django.db import models
import uuid

class TimeStampedModel(models.Model):
    """Abstract base class with timestamp fields"""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True
        ordering = ['-created_at']


class UUIDModel(models.Model):
    """Abstract base class with UUID primary key"""
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Abstract base class for soft deletes"""
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        abstract = True


class SlugMixin(models.Model):
    """Abstract base class with slug field"""
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="URL-friendly version of the name"
    )
    
    class Meta:
        abstract = True


class PublishableModel(models.Model):
    """Abstract base class for content that can be published/unpublished"""
    is_published = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this content is visible to users"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        abstract = True


class FeaturedContentMixin(models.Model):
    """Abstract base class for suggested/featured content"""
    is_featured = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Featured in suggested content catalog"
    )
    featured_order = models.IntegerField(
        default=0,
        help_text="Display order for featured content (higher = more prominent)"
    )
    
    class Meta:
        abstract = True