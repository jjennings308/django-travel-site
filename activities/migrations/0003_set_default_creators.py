from django.db import migrations
from django.conf import settings

def set_creators(apps, schema_editor):
    Activity = apps.get_model('activities', 'Activity')
    User = apps.get_model(settings.AUTH_USER_MODEL)

    default_user = User.objects.filter(is_staff=True).first()

    if default_user:
        for activity in Activity.objects.filter(created_by__isnull=True):
            activity.created_by = default_user
            activity.source = 'staff'
            activity.visibility = 'public'
            activity.approval_status = 'approved'
            activity.specificity_level = 'general'
            activity.save()

class Migration(migrations.Migration):
    dependencies = [
        ('activities', '0002_useractivitybookmark_alter_activity_options_and_more'),
    ]

    operations = [
        migrations.RunPython(set_creators),
    ]