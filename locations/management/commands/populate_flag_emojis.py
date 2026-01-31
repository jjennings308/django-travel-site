# locations/management/commands/populate_flag_emojis.py
"""
Management command to populate flag_emoji field for all countries
based on their ISO codes.

Usage:
    python manage.py populate_flag_emojis
    python manage.py populate_flag_emojis --overwrite  # Update existing flags too
"""

from django.core.management.base import BaseCommand
from locations.models import Country


def iso_to_flag_emoji(iso_code):
    """Convert 2-letter ISO code to flag emoji"""
    if not iso_code or len(iso_code) != 2:
        return ''
    
    iso_code = iso_code.upper()
    # Convert ISO code to flag emoji using Unicode regional indicator symbols
    flag = ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in iso_code)
    return flag


class Command(BaseCommand):
    help = 'Populate flag_emoji field for all countries based on ISO codes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite existing flag emojis',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        overwrite = options['overwrite']
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.SUCCESS('Starting flag emoji population...'))
        
        # Get countries to update
        if overwrite:
            countries = Country.objects.filter(iso_code__isnull=False).exclude(iso_code='')
            self.stdout.write(f'Updating ALL {countries.count()} countries (overwrite mode)')
        else:
            countries = Country.objects.filter(
                iso_code__isnull=False,
                flag_emoji=''
            ).exclude(iso_code='')
            self.stdout.write(f'Updating {countries.count()} countries without flags')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be saved'))
        
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for country in countries:
            try:
                # Generate flag from ISO code
                flag = iso_to_flag_emoji(country.iso_code)
                
                if not flag:
                    self.stdout.write(
                        self.style.ERROR(f'  ✗ {country.name} ({country.iso_code}) - Invalid ISO code')
                    )
                    error_count += 1
                    continue
                
                if not dry_run:
                    old_flag = country.flag_emoji
                    country.flag_emoji = flag
                    country.save(update_fields=['flag_emoji'])
                    
                    if old_flag and old_flag != flag:
                        self.stdout.write(
                            self.style.WARNING(f'  ↻ {country.name}: {old_flag} → {flag}')
                        )
                    else:
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ {country.name}: {flag}')
                        )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f'  [DRY RUN] Would set {country.name} to {flag}')
                    )
                
                updated_count += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error updating {country.name}: {str(e)}')
                )
                error_count += 1
        
        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(self.style.SUCCESS(f'✓ Successfully processed: {updated_count}'))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'✗ Errors: {error_count}'))
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f'○ Skipped: {skipped_count}'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nNo changes were made (dry run mode)'))
            self.stdout.write('Run without --dry-run to apply changes')
        else:
            self.stdout.write(self.style.SUCCESS('\nFlag emojis have been updated!'))
