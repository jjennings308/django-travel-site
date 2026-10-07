# accounts/migrations/0010_migrate_existing_users.py
# Data migration to handle existing users - convert email usernames to proper usernames

from django.db import migrations
import re


def generate_username_from_email(email):
    """Generate a username from email address"""
    # Take part before @
    base = email.split('@')[0]
    # Remove any non-alphanumeric characters except underscore
    base = re.sub(r'[^\w]', '_', base)
    # Ensure it's lowercase
    base = base.lower()
    # Limit to 30 characters
    return base[:30]


def migrate_usernames_forward(apps, schema_editor):
    """
    For existing users whose username is their email, generate proper usernames
    """
    User = apps.get_model('accounts', 'User')
    
    # Find users where username contains @ (i.e., is an email)
    users_with_email_usernames = User.objects.filter(username__contains='@')
    
    for user in users_with_email_usernames:
        # Generate base username from email
        base_username = generate_username_from_email(user.username)
        
        # Ensure uniqueness
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exclude(pk=user.pk).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Update the username
        user.username = username
        user.save(update_fields=['username'])
        
        print(f"Migrated user {user.email}: username changed from {user.username} to {username}")


def migrate_usernames_reverse(apps, schema_editor):
    """
    Reverse migration - set usernames back to emails
    This is destructive and should only be used if absolutely necessary
    """
    User = apps.get_model('accounts', 'User')
    
    # For all users, set username to their email
    for user in User.objects.all():
        user.username = user.email
        user.save(update_fields=['username'])


def set_subscription_tiers(apps, schema_editor):
    """
    Set subscription tier based on existing is_premium field
    """
    User = apps.get_model('accounts', 'User')
    
    for user in User.objects.all():
        if user.is_premium:
            user.subscription_tier = 'gold'
        else:
            user.subscription_tier = 'free'
        user.save(update_fields=['subscription_tier'])


def reverse_subscription_tiers(apps, schema_editor):
    """
    Reverse - set all to free
    """
    User = apps.get_model('accounts', 'User')
    User.objects.all().update(subscription_tier='free')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_role_system'),
    ]

    operations = [
        # First migrate usernames
        migrations.RunPython(
            migrate_usernames_forward,
            reverse_code=migrate_usernames_reverse
        ),
        
        # Then set subscription tiers based on is_premium
        migrations.RunPython(
            set_subscription_tiers,
            reverse_code=reverse_subscription_tiers
        ),
    ]
