from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from locations.models import Country
from approval_system.models import ApprovalStatus

User = get_user_model()


class Command(BaseCommand):
    """
    Seed/repair Countries (offline & idempotent).
    
    Now includes approval system integration - all imported countries
    are automatically marked as APPROVED since these are system-level imports.
    """

    help = "Seed/repair Countries (baseline dataset; offline & idempotent with auto-approval)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-detailed",
            action="store_true",
            help="Skip seeding the curated country list (no-op).",
        )
        parser.add_argument(
            "--approved-by",
            type=str,
            default=None,
            help="Username of the user to mark as approver. If not provided, uses first superuser.",
        )

    def _get_approver(self, username=None):
        """Get the user who will be marked as the approver for system imports"""
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"User '{username}' not found. Trying first superuser..."
                ))
        
        # Fallback to first superuser
        superuser = User.objects.filter(is_superuser=True).first()
        if superuser:
            return superuser
        
        return None

    def handle(self, *args, **options):
        if options.get("skip_detailed", False):
            self.stdout.write(self.style.WARNING("Skipped (per --skip-detailed)."))
            return

        # Get approver user for marking imports as approved
        approver = self._get_approver(options.get("approved_by"))
        if not approver:
            self.stdout.write(self.style.ERROR(
                "No approver found. Please create a superuser first or specify --approved-by <username>."
            ))
            self.stdout.write(self.style.ERROR(
                "Hint: Run 'python manage.py createsuperuser' to create one."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Using approver: {approver.username} (ID: {approver.id})"
        ))

        # Curated list of countries for the travel site
        countries = [
            # North America
            ("US", "USA", "United States", "North America", "en-US"),
            ("CA", "CAN", "Canada", "North America", "en-CA"),
            ("MX", "MEX", "Mexico", "North America", "es-MX"),
            ("CR", "CRI", "Costa Rica", "North America", "es-CR"),
            
            # Europe
            ("GB", "GBR", "United Kingdom", "Europe", "en-GB"),
            ("FR", "FRA", "France", "Europe", "fr-FR"),
            ("DE", "DEU", "Germany", "Europe", "de-DE"),
            ("IT", "ITA", "Italy", "Europe", "it-IT"),
            ("ES", "ESP", "Spain", "Europe", "es-ES"),
            ("PT", "PRT", "Portugal", "Europe", "pt-PT"),
            ("NL", "NLD", "Netherlands", "Europe", "nl-NL"),
            ("BE", "BEL", "Belgium", "Europe", "nl-BE"),
            ("CH", "CHE", "Switzerland", "Europe", "de-CH"),
            ("AT", "AUT", "Austria", "Europe", "de-AT"),
            ("GR", "GRC", "Greece", "Europe", "el-GR"),
            ("NO", "NOR", "Norway", "Europe", "no-NO"),
            ("SE", "SWE", "Sweden", "Europe", "sv-SE"),
            ("DK", "DNK", "Denmark", "Europe", "da-DK"),
            ("FI", "FIN", "Finland", "Europe", "fi-FI"),
            ("IE", "IRL", "Ireland", "Europe", "en-IE"),
            ("IS", "ISL", "Iceland", "Europe", "is-IS"),
            
            # Asia
            ("JP", "JPN", "Japan", "Asia", "ja-JP"),
            ("CN", "CHN", "China", "Asia", "zh-CN"),
            ("TH", "THA", "Thailand", "Asia", "th-TH"),
            ("VN", "VNM", "Vietnam", "Asia", "vi-VN"),
            ("IN", "IND", "India", "Asia", "hi-IN"),
            ("KR", "KOR", "South Korea", "Asia", "ko-KR"),
            ("ID", "IDN", "Indonesia", "Asia", "id-ID"),
            ("MY", "MYS", "Malaysia", "Asia", "ms-MY"),
            ("SG", "SGP", "Singapore", "Asia", "en-SG"),
            ("PH", "PHL", "Philippines", "Asia", "en-PH"),
            
            # Oceania
            ("AU", "AUS", "Australia", "Oceania", "en-AU"),
            ("NZ", "NZL", "New Zealand", "Oceania", "en-NZ"),
            
            # South America
            ("BR", "BRA", "Brazil", "South America", "pt-BR"),
            ("AR", "ARG", "Argentina", "South America", "es-AR"),
            ("CL", "CHL", "Chile", "South America", "es-CL"),
            ("PE", "PER", "Peru", "South America", "es-PE"),
            ("CO", "COL", "Colombia", "South America", "es-CO"),
            
            # Africa
            ("ZA", "ZAF", "South Africa", "Africa", "en-ZA"),
            ("EG", "EGY", "Egypt", "Africa", "ar-EG"),
            ("MA", "MAR", "Morocco", "Africa", "ar-MA"),
            ("KE", "KEN", "Kenya", "Africa", "en-KE"),
        ]

        created = 0
        updated = 0
        approved_count = 0
        errors = 0

        for iso2, iso3, name, continent, locale in countries:
            try:
                country, was_created = Country.objects.update_or_create(
                    iso_code=iso2,
                    defaults={
                        "iso3_code": iso3,
                        "name": name,
                        "continent": continent,
                        # Approval fields - mark as approved for system imports
                        "approval_status": ApprovalStatus.APPROVED,
                        "submitted_by": approver,
                        "submitted_at": timezone.now(),
                        "reviewed_by": approver,
                        "reviewed_at": timezone.now(),
                    },
                )

                if was_created:
                    created += 1
                    approved_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ Created & Approved: {name} ({iso2})"
                    ))
                else:
                    updated += 1
                    # If updating an existing country, ensure it's approved
                    if country.approval_status != ApprovalStatus.APPROVED:
                        country.approval_status = ApprovalStatus.APPROVED
                        country.reviewed_by = approver
                        country.reviewed_at = timezone.now()
                        country.save()
                        approved_count += 1
                    self.stdout.write(self.style.WARNING(
                        f"↻ Updated: {name} ({iso2})"
                    ))

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(
                    f"✗ Error for {name} ({iso2}): {e}"
                ))

        # Summary
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Countries seed/repair complete!"))
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.WARNING(f"Updated: {updated}"))
        self.stdout.write(self.style.SUCCESS(f"Auto-Approved: {approved_count}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors: {errors}"))
        self.stdout.write(self.style.SUCCESS(f"All imports marked as approved by: {approver.username}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
