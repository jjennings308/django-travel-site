# accounts/migrations/0009_role_system.py
# Generated manually for role system implementation

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_alter_user_options'),
    ]

    operations = [
        # Add username field validators
        migrations.AlterField(
            model_name='user',
            name='username',
            field=models.CharField(
                help_text='Unique username for your profile URL',
                max_length=30,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        '^[a-zA-Z0-9_]+$',
                        'Username can only contain letters, numbers, and underscores'
                    )
                ]
            ),
        ),
        
        # Add subscription tier fields
        migrations.AddField(
            model_name='user',
            name='subscription_tier',
            field=models.CharField(
                choices=[
                    ('free', 'Free Member'),
                    ('plus', 'Plus Member'),
                    ('gold', 'Gold Member')
                ],
                default='free',
                help_text='Membership subscription level',
                max_length=10
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='subscription_expires',
            field=models.DateTimeField(
                blank=True,
                help_text='When paid subscription expires (null for free tier)',
                null=True
            ),
        ),
        
        # Remove old is_premium field (replaced by subscription_tier)
        # migrations.RemoveField(
        #     model_name='user',
        #     name='premium_expires',
        # ),
        # NOTE: Keeping is_premium and premium_expires for now for backward compatibility
        # They will be handled by the @property is_premium
        
        # Create RoleRequest model
        migrations.CreateModel(
            name='RoleRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('requested_role', models.CharField(
                    choices=[('vendor', 'Vendor'), ('content_provider', 'Content Provider')],
                    max_length=20
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending Review'),
                        ('approved', 'Approved'),
                        ('rejected', 'Rejected'),
                        ('revoked', 'Revoked')
                    ],
                    default='pending',
                    max_length=20
                )),
                ('business_name', models.CharField(
                    blank=True,
                    help_text='Business/brand name (for vendors)',
                    max_length=200
                )),
                ('business_description', models.TextField(
                    help_text='Tell us about your business/content'
                )),
                ('website', models.URLField(blank=True)),
                ('business_license', models.CharField(
                    blank=True,
                    help_text='Business license number (if applicable)',
                    max_length=100
                )),
                ('supporting_documents', models.FileField(
                    blank=True,
                    help_text='Upload verification documents (license, portfolio, etc.)',
                    null=True,
                    upload_to='role_requests/%Y/%m/'
                )),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(
                    blank=True,
                    help_text='Internal notes about approval/rejection'
                )),
                ('rejection_reason', models.TextField(
                    blank=True,
                    help_text='Reason shown to user if rejected'
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_role_requests',
                    to=settings.AUTH_USER_MODEL
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='role_requests',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'db_table': 'role_requests',
                'ordering': ['-created_at'],
            },
        ),
        
        # Create VendorProfile model
        migrations.CreateModel(
            name='VendorProfile',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='vendor_profile',
                    serialize=False,
                    to=settings.AUTH_USER_MODEL
                )),
                ('business_name', models.CharField(max_length=200)),
                ('business_description', models.TextField()),
                ('business_license', models.CharField(blank=True, max_length=100)),
                ('website', models.URLField(blank=True)),
                ('verification_status', models.CharField(
                    choices=[
                        ('pending', 'Pending Verification'),
                        ('verified', 'Verified'),
                        ('suspended', 'Suspended')
                    ],
                    default='verified',
                    max_length=20
                )),
                ('total_listings', models.IntegerField(default=0)),
                ('average_rating', models.DecimalField(
                    decimal_places=2,
                    default=0.0,
                    max_digits=3
                )),
                ('total_bookings', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'vendor_profiles',
            },
        ),
        
        # Create ContentProviderProfile model
        migrations.CreateModel(
            name='ContentProviderProfile',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='content_provider_profile',
                    serialize=False,
                    to=settings.AUTH_USER_MODEL
                )),
                ('portfolio_url', models.URLField(blank=True)),
                ('bio', models.TextField(help_text='Your background and expertise')),
                ('specializations', models.JSONField(
                    default=list,
                    help_text='List of content specializations (photography, writing, video, etc.)'
                )),
                ('total_contributions', models.IntegerField(default=0)),
                ('content_rating', models.DecimalField(
                    decimal_places=2,
                    default=0.0,
                    max_digits=3
                )),
            ],
            options={
                'db_table': 'content_provider_profiles',
            },
        ),
        
        # Add indexes for RoleRequest
        migrations.AddIndex(
            model_name='rolerequest',
            index=models.Index(
                fields=['user', 'requested_role', 'status'],
                name='role_reques_user_id_a1b2c3_idx'
            ),
        ),
        migrations.AddIndex(
            model_name='rolerequest',
            index=models.Index(
                fields=['status', 'created_at'],
                name='role_reques_status_d4e5f6_idx'
            ),
        ),
        
        # Add constraint to prevent duplicate pending requests
        migrations.AddConstraint(
            model_name='rolerequest',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='pending'),
                fields=('user', 'requested_role'),
                name='unique_pending_role_request'
            ),
        ),
    ]
