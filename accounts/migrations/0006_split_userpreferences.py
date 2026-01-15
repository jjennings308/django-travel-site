# accounts/migrations/0006_split_userpreferences.py
# Create this file manually or run: python manage.py makemigrations accounts --empty --name split_userpreferences

from django.db import migrations


def split_preferences_forward(apps, schema_editor):
    """
    Copy data from UserPreferences to TravelPreferences and AccountSettings
    """
    UserPreferences = apps.get_model('accounts', 'UserPreferences')
    TravelPreferences = apps.get_model('accounts', 'TravelPreferences')
    AccountSettings = apps.get_model('accounts', 'AccountSettings')
    
    for old_pref in UserPreferences.objects.all():
        # Create TravelPreferences
        TravelPreferences.objects.create(
            user=old_pref.user,
            budget_preference=old_pref.budget_preference,
            travel_styles=old_pref.travel_styles,
            travel_pace=old_pref.travel_pace,
            preferred_activities=old_pref.preferred_activities,
            fitness_level=old_pref.fitness_level,
            mobility_restrictions=old_pref.mobility_restrictions,
            created_at=old_pref.created_at,
            updated_at=old_pref.updated_at,
        )
        
        # Create AccountSettings
        AccountSettings.objects.create(
            user=old_pref.user,
            email_notifications=old_pref.email_notifications,
            push_notifications=old_pref.push_notifications,
            marketing_emails=old_pref.marketing_emails,
            notify_bucket_list_reminders=old_pref.notify_bucket_list_reminders,
            notify_trip_updates=old_pref.notify_trip_updates,
            notify_event_reminders=old_pref.notify_event_reminders,
            notify_friend_activity=old_pref.notify_friend_activity,
            notify_recommendations=old_pref.notify_recommendations,
            language=old_pref.language,
            units=old_pref.units,
            preferred_currency=old_pref.preferred_currency,
            timezone=old_pref.timezone,
            theme=getattr(old_pref, 'theme', 'default'),
            created_at=old_pref.created_at,
            updated_at=old_pref.updated_at,
        )


def split_preferences_reverse(apps, schema_editor):
    """
    For rollback - just delete the new records
    """
    TravelPreferences = apps.get_model('accounts', 'TravelPreferences')
    AccountSettings = apps.get_model('accounts', 'AccountSettings')
    
    TravelPreferences.objects.all().delete()
    AccountSettings.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        # This will automatically use the last migration in the accounts app
        ('accounts', '0005_accountsettings_travelpreferences_and_more'),
    ]

    operations = [
        migrations.RunPython(
            split_preferences_forward,
            reverse_code=split_preferences_reverse
        ),
    ]
