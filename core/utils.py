# core/utils.py
from django.utils.text import slugify
from django.utils import timezone

def generate_unique_slug(model_class, title, instance_id=None):
    """Generate a unique slug for a model instance"""
    slug = slugify(title)
    unique_slug = slug
    num = 1
    
    while model_class.objects.filter(slug=unique_slug).exclude(id=instance_id).exists():
        unique_slug = f"{slug}-{num}"
        num += 1
    
    return unique_slug


def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = timezone.now().date()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )