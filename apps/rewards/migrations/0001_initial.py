# rewards/migrations/0001_initial.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import uuid


def create_initial_programs(apps, schema_editor):
    """Create popular rewards programs"""
    RewardsProgram = apps.get_model('rewards', 'RewardsProgram')
    
    programs = [
        # ===== AIRLINES =====
        {
            'name': 'AAdvantage',
            'company': 'American Airlines',
            'program_type': 'airline',
            'website': 'https://www.aa.com/aadvantage',
            'tier_names': ['Gold', 'Platinum', 'Platinum Pro', 'Executive Platinum'],
            'description': 'Earn miles on American Airlines and partner flights',
        },
        {
            'name': 'MileagePlus',
            'company': 'United Airlines',
            'program_type': 'airline',
            'website': 'https://www.united.com/mileageplus',
            'tier_names': ['Silver', 'Gold', 'Platinum', '1K'],
            'description': 'United Airlines frequent flyer program',
        },
        {
            'name': 'SkyMiles',
            'company': 'Delta Air Lines',
            'program_type': 'airline',
            'website': 'https://www.delta.com/skymiles',
            'tier_names': ['Silver', 'Gold', 'Platinum', 'Diamond'],
            'description': 'Delta\'s award-winning loyalty program',
        },
        {
            'name': 'Rapid Rewards',
            'company': 'Southwest Airlines',
            'program_type': 'airline',
            'website': 'https://www.southwest.com/rapidrewards',
            'tier_names': ['A-List', 'A-List Preferred'],
            'description': 'Points-based program with no blackout dates',
        },
        {
            'name': 'Executive Club',
            'company': 'British Airways',
            'program_type': 'airline',
            'website': 'https://www.britishairways.com/executive-club',
            'tier_names': ['Blue', 'Bronze', 'Silver', 'Gold'],
            'description': 'Avios points program for British Airways',
        },
        {
            'name': 'Flying Blue',
            'company': 'Air France-KLM',
            'program_type': 'airline',
            'website': 'https://www.flyingblue.com',
            'tier_names': ['Explorer', 'Silver', 'Gold', 'Platinum'],
            'description': 'Joint loyalty program for Air France and KLM',
        },
        {
            'name': 'Aeroplan',
            'company': 'Air Canada',
            'program_type': 'airline',
            'website': 'https://www.aircanada.com/aeroplan',
            'tier_names': ['25K', '35K', '50K', '75K', 'Super Elite'],
            'description': 'Air Canada\'s frequent flyer program',
        },
        
        # ===== HOTELS =====
        {
            'name': 'Bonvoy',
            'company': 'Marriott',
            'program_type': 'hotel',
            'website': 'https://www.marriott.com/loyalty',
            'tier_names': ['Silver', 'Gold', 'Platinum', 'Titanium', 'Ambassador'],
            'description': 'Marriott\'s unified loyalty program across 30+ brands',
        },
        {
            'name': 'Honors',
            'company': 'Hilton',
            'program_type': 'hotel',
            'website': 'https://www.hilton.com/honors',
            'tier_names': ['Member', 'Silver', 'Gold', 'Diamond'],
            'description': 'Hilton\'s points-based rewards program',
        },
        {
            'name': 'One Key',
            'company': 'Expedia Group',
            'program_type': 'hotel',
            'website': 'https://www.expedia.com/onekey',
            'tier_names': ['Blue', 'Silver', 'Gold'],
            'description': 'Combined rewards for Expedia, Hotels.com, and Vrbo',
        },
        {
            'name': 'Rewards',
            'company': 'IHG',
            'program_type': 'hotel',
            'website': 'https://www.ihg.com/rewards',
            'tier_names': ['Club', 'Gold Elite', 'Platinum Elite', 'Diamond Elite'],
            'description': 'IHG Hotels & Resorts loyalty program',
        },
        {
            'name': 'World of Hyatt',
            'company': 'Hyatt',
            'program_type': 'hotel',
            'website': 'https://world.hyatt.com',
            'tier_names': ['Member', 'Discoverist', 'Explorist', 'Globalist'],
            'description': 'Hyatt\'s flexible points program',
        },
        {
            'name': 'Wyndham Rewards',
            'company': 'Wyndham Hotels',
            'program_type': 'hotel',
            'website': 'https://www.wyndhamhotels.com/wyndham-rewards',
            'tier_names': ['Blue', 'Gold', 'Platinum', 'Diamond'],
            'description': 'Simple points program with free night redemptions',
        },
        {
            'name': 'ALL - Accor Live Limitless',
            'company': 'Accor',
            'program_type': 'hotel',
            'website': 'https://all.accor.com',
            'tier_names': ['Classic', 'Silver', 'Gold', 'Platinum', 'Diamond'],
            'description': 'Accor\'s lifestyle loyalty program',
        },
        
        # ===== CAR RENTALS =====
        {
            'name': 'Emerald Club',
            'company': 'National Car Rental',
            'program_type': 'car_rental',
            'website': 'https://www.nationalcar.com/emeraldclub',
            'tier_names': ['Emerald Club', 'Executive'],
            'description': 'Skip the counter and choose your own car',
        },
        {
            'name': 'Gold Plus Rewards',
            'company': 'Hertz',
            'program_type': 'car_rental',
            'website': 'https://www.hertz.com/gold',
            'tier_names': ['Gold', 'Five Star', 'President\'s Circle'],
            'description': 'Earn points and enjoy expedited service',
        },
        {
            'name': 'Preferred',
            'company': 'Avis',
            'program_type': 'car_rental',
            'website': 'https://www.avis.com/preferred',
            'tier_names': ['Preferred', 'Preferred Plus', 'Chairman\'s Club'],
            'description': 'Skip the counter with Avis Preferred',
        },
        {
            'name': 'Budget Fastbreak',
            'company': 'Budget',
            'program_type': 'car_rental',
            'website': 'https://www.budget.com/fastbreak',
            'tier_names': [],
            'description': 'Fast, no-paperwork rentals',
        },
        {
            'name': 'Express Deal',
            'company': 'Enterprise',
            'program_type': 'car_rental',
            'website': 'https://www.enterprise.com',
            'tier_names': [],
            'description': 'Enterprise loyalty program',
        },
        
        # ===== TRAINS =====
        {
            'name': 'Guest Rewards',
            'company': 'Amtrak',
            'program_type': 'train',
            'website': 'https://www.amtrak.com/guestrewards',
            'tier_names': ['Select', 'Select Plus', 'Select Executive'],
            'description': 'Amtrak\'s points-based rewards program',
        },
        
        # ===== CRUISE LINES =====
        {
            'name': 'Crown & Anchor Society',
            'company': 'Royal Caribbean',
            'program_type': 'cruise',
            'website': 'https://www.royalcaribbean.com/loyalty',
            'tier_names': ['Gold', 'Platinum', 'Emerald', 'Diamond', 'Diamond Plus', 'Pinnacle Club'],
            'description': 'Royal Caribbean\'s cruise loyalty program',
        },
        {
            'name': 'Carnival Players Club',
            'company': 'Carnival Cruise Line',
            'program_type': 'cruise',
            'website': 'https://www.carnival.com/vifp-club',
            'tier_names': ['Blue', 'Red', 'Gold', 'Platinum', 'Diamond'],
            'description': 'VIFP (Very Important Fun Person) Club',
        },
        {
            'name': 'Captains Circle',
            'company': 'Princess Cruises',
            'program_type': 'cruise',
            'website': 'https://www.princess.com/learn/faq_answer/loyalty_rewards/',
            'tier_names': ['Gold', 'Ruby', 'Platinum', 'Elite'],
            'description': 'Princess Cruises loyalty benefits',
        },
    ]
    
    for idx, prog_data in enumerate(programs):
        RewardsProgram.objects.get_or_create(
            name=prog_data['name'],
            company=prog_data['company'],
            defaults={
                'program_type': prog_data['program_type'],
                'website': prog_data.get('website', ''),
                'tier_names': prog_data.get('tier_names', []),
                'description': prog_data.get('description', ''),
                'is_active': True,
                'display_order': idx,
            }
        )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RewardsProgram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(help_text='e.g., United MileagePlus, Marriott Bonvoy', max_length=200)),
                ('program_type', models.CharField(choices=[('airline', 'Airline'), ('hotel', 'Hotel'), ('car_rental', 'Car Rental'), ('credit_card', 'Credit Card'), ('train', 'Train/Rail'), ('cruise', 'Cruise Line'), ('other', 'Other')], default='other', max_length=20)),
                ('company', models.CharField(help_text='e.g., United Airlines, Marriott', max_length=200)),
                ('website', models.URLField(blank=True)),
                ('logo', models.ImageField(blank=True, null=True, upload_to='rewards_logos/')),
                ('tier_names', models.JSONField(blank=True, default=list, help_text="List of tier names, e.g., ['Silver', 'Gold', 'Platinum']")),
                ('description', models.TextField(blank=True, help_text='Brief description of the program')),
                ('is_active', models.BooleanField(default=True, help_text='Is this program still active/operational?')),
                ('display_order', models.IntegerField(default=0, help_text='Order to display in lists (lower = first)')),
            ],
            options={
                'db_table': 'rewards_programs',
                'ordering': ['display_order', 'company', 'name'],
            },
        ),
        migrations.CreateModel(
            name='UserRewardsMembership',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('member_number', models.CharField(help_text='Your membership/account number', max_length=100)),
                ('member_name', models.CharField(blank=True, help_text='Name on the account (if different from profile)', max_length=200)),
                ('current_tier', models.CharField(blank=True, help_text='e.g., Gold, Platinum', max_length=50)),
                ('points_balance', models.IntegerField(blank=True, help_text='Current points/miles balance (optional)', null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ('tier_expires', models.DateField(blank=True, help_text='When current tier status expires', null=True)),
                ('username', models.CharField(blank=True, help_text='Login username for this program', max_length=200)),
                ('is_primary', models.BooleanField(default=False, help_text='Primary program of this type (e.g., preferred airline)')),
                ('notes', models.TextField(blank=True, help_text='Personal notes about this membership')),
                ('show_on_profile', models.BooleanField(default=True, help_text='Show this membership on your public profile')),
                ('display_order', models.IntegerField(default=0, help_text='Order to display on profile (lower = first)')),
                ('notify_on_expiration', models.BooleanField(default=True, help_text='Notify when tier status is about to expire')),
                ('expiration_notice_days', models.IntegerField(default=30, help_text='Days before expiration to send notification', validators=[django.core.validators.MinValueValidator(1)])),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='rewards.rewardsprogram')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rewards_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Rewards Membership',
                'verbose_name_plural': 'Rewards Memberships',
                'db_table': 'user_rewards_memberships',
                'ordering': ['display_order', 'program__company'],
            },
        ),
        migrations.AddConstraint(
            model_name='rewardsprogram',
            constraint=models.UniqueConstraint(fields=('name', 'company'), name='rewards_program_unique_name_company'),
        ),
        migrations.AddIndex(
            model_name='rewardsprogram',
            index=models.Index(fields=['program_type', 'is_active'], name='rewards_pro_program_idx'),
        ),
        migrations.AddIndex(
            model_name='rewardsprogram',
            index=models.Index(fields=['display_order'], name='rewards_pro_display_idx'),
        ),
        migrations.AddConstraint(
            model_name='userrewardsmembership',
            constraint=models.UniqueConstraint(fields=('user', 'program'), name='user_rewards_unique_user_program'),
        ),
        migrations.AddIndex(
            model_name='userrewardsmembership',
            index=models.Index(fields=['user', 'is_primary'], name='user_reward_user_id_primary_idx'),
        ),
        migrations.AddIndex(
            model_name='userrewardsmembership',
            index=models.Index(fields=['user', 'show_on_profile'], name='user_reward_user_id_profile_idx'),
        ),
        migrations.AddIndex(
            model_name='userrewardsmembership',
            index=models.Index(fields=['user', 'program'], name='user_reward_user_id_program_idx'),
        ),
        migrations.RunPython(create_initial_programs, reverse_code=migrations.RunPython.noop),
    ]