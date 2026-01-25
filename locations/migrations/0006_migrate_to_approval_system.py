# locations/migrations/0006_migrate_to_approval_system.py

from django.db import migrations

def migrate_statuses(apps, schema_editor):
    """Map old status field to new approval_status"""
    
    Country = apps.get_model('locations', 'Country')
    
    status_mapping = {
        'pending': 'pending',
        'approved': 'approved',
        'rejected': 'rejected',
        'needs_changes': 'changes_requested',
    }
    
    for country in Country.objects.all():
        # Map status
        if country.status in status_mapping:
            country.approval_status = status_mapping[country.status]
        
        # Map submitted_by if it exists
        if hasattr(country, 'submitted_by_old') and country.submitted_by_old:
            country.submitted_by = country.submitted_by_old
        
        # Map reviewed_by
        if hasattr(country, 'reviewed_by_old') and country.reviewed_by_old:
            country.reviewed_by = country.reviewed_by_old
        
        # Map timestamps
        if hasattr(country, 'reviewed_at_old'):
            country.reviewed_at = country.reviewed_at_old
        
        country.save()


def reverse_migrate(apps, schema_editor):
    """Reverse migration if needed"""
    Country = apps.get_model('locations', 'Country')
    
    for country in Country.objects.all():
        # Map back to old fields
        if country.approval_status == 'pending':
            country.status = 'pending'
        # ... etc
        country.save()


class Migration(migrations.Migration):
    dependencies = [
        ('locations', '0005_city_featured_media_city_review_notes_and_more'),
        ('approval_system', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(migrate_statuses, reverse_migrate),
    ]