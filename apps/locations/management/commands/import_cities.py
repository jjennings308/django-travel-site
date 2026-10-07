from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from locations.models import CapitalType, City, Country, Region
from approval_system.models import ApprovalStatus

User = get_user_model()


class Command(BaseCommand):
    """
    Seed/repair Cities (curated set for US/MX/CR/DE/AT; offline & idempotent).
    
    Now includes approval system integration - all imported cities are
    automatically marked as APPROVED since these are system-level imports.
    """

    help = "Seed/repair Cities (curated set for US/MX/CR/DE/AT; offline & idempotent with auto-approval)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-detailed",
            action="store_true",
            help="Skip seeding the curated city lists (no-op).",
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
            return

        self.stdout.write(self.style.SUCCESS(
            f"Using approver: {approver.username} (ID: {approver.id})"
        ))

        # Tuple formats supported:
        #   (city_name, region_name, lat, lon, description)
        #   (city_name, region_name, lat, lon, description, capital_type)
        # Use capital_type=None for non-capitals.
        cities_by_country = {
            "US": [
                (
                    "Washington",
                    "District of Columbia",
                    38.8951,
                    -77.0364,
                    "Capital of the United States (Washington, DC).",
                    CapitalType.COUNTRY,
                ),
                ("New York City", "New York", 40.7128, -74.0060, "Largest city in the United States.", None),
                ("Los Angeles", "California", 34.0522, -118.2437, "Major city in Southern California.", None),
                ("Chicago", "Illinois", 41.8781, -87.6298, "Major city on Lake Michigan.", None),
                ("Miami", "Florida", 25.7617, -80.1918, "Major coastal city in Florida.", None),
            ],
            "MX": [
                ("Mexico City", "Mexico City", 19.4326, -99.1332, "Capital of Mexico.", CapitalType.COUNTRY),
                ("Guadalajara", "Jalisco", 20.6597, -103.3496, "Major city in western Mexico.", None),
                ("Monterrey", "Nuevo León", 25.6866, -100.3161, "Major city in northeastern Mexico.", None),
                ("Cancún", "Quintana Roo", 21.1619, -86.8515, "Major tourism hub on the Caribbean coast.", None),
            ],
            "CR": [
                ("San José", "San José", 9.9281, -84.0907, "Capital of Costa Rica.", CapitalType.COUNTRY),
                ("Liberia", "Guanacaste", 10.6346, -85.4377, "Gateway city to Guanacaste beaches.", None),
                ("Limón", "Limón", 9.9907, -83.0333, "Port city on the Caribbean coast.", None),
            ],
            "DE": [
                ("Berlin", "Berlin", 52.5200, 13.4050, "Capital of Germany.", CapitalType.BOTH),
                ("Munich", "Bavaria", 48.1351, 11.5820, "Major city in Bavaria (München).", None),
                ("Frankfurt", "Hesse", 50.1109, 8.6821, "Major finance hub (Frankfurt am Main).", None),
                ("Hamburg", "Hamburg", 53.5511, 9.9937, "Major port city in northern Germany.", None),
                (
                    "Cologne",
                    "North Rhine-Westphalia",
                    50.9375,
                    6.9603,
                    "Major city in NRW (Köln).",
                    None,
                ),
            ],
            "AT": [
                ("Vienna", "Vienna", 48.2082, 16.3738, "Capital of Austria (Wien).", CapitalType.BOTH),
                ("Salzburg", "Salzburg", 47.8095, 13.0550, "Historic city and Mozart's birthplace.", None),
                ("Innsbruck", "Tyrol", 47.2692, 11.4041, "Major city in Tyrol.", None),
                ("Graz", "Styria", 47.0707, 15.4395, "Capital of Styria.", None),
            ],
        }

        created = 0
        updated = 0
        approved_count = 0
        errors = 0
        missing_countries = 0

        for iso2, city_rows in cities_by_country.items():
            try:
                country = Country.objects.get(iso_code=iso2)
            except Country.DoesNotExist:
                missing_countries += 1
                self.stdout.write(self.style.WARNING(f"⚠ Country not found: {iso2} (skipping cities)"))
                continue

            for row in city_rows:
                try:
                    if len(row) == 5:
                        city_name, region_name, lat, lon, description = row
                        capital_type = None
                    elif len(row) == 6:
                        city_name, region_name, lat, lon, description, capital_type = row
                    else:
                        raise ValueError(
                            f"City tuple must have 5 or 6 values, got {len(row)}: {row!r}"
                        )

                    # Ensure Region exists (safety net)
                    region, _ = Region.objects.get_or_create(
                        country=country,
                        name=region_name,
                        defaults={
                            "code": (region_name[:3].upper() if region_name else country.iso_code),
                            "description": f"Auto-created region to support city seeding for {country.name}.",
                            # Approval fields for auto-created regions
                            "approval_status": ApprovalStatus.APPROVED,
                            "submitted_by": approver,
                            "submitted_at": timezone.now(),
                            "reviewed_by": approver,
                            "reviewed_at": timezone.now(),
                        },
                    )

                    city, was_created = City.objects.update_or_create(
                        country=country,
                        name=city_name,
                        defaults={
                            "region": region,
                            "latitude": Decimal(str(lat)),
                            "longitude": Decimal(str(lon)),
                            "description": description,
                            "timezone": "",  # NOT NULL column; blank string is safe
                            "population": None,
                            "elevation": None,
                            "capital_type": capital_type,  # City.save() derives is_capital
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
                        self.stdout.write(self.style.SUCCESS(f"✓ Created & Approved: {city_name}, {iso2}"))
                    else:
                        updated += 1
                        # Ensure existing city is approved
                        if city.approval_status != ApprovalStatus.APPROVED:
                            city.approval_status = ApprovalStatus.APPROVED
                            city.reviewed_by = approver
                            city.reviewed_at = timezone.now()
                            city.save()
                            approved_count += 1
                        self.stdout.write(self.style.WARNING(f"↻ Updated: {city_name}, {iso2}"))

                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.ERROR(f"✗ Error seeding city row {row!r} for {iso2}: {e}")
                    )

            self.stdout.write(self.style.SUCCESS(f"✓ Done: {country.name} ({iso2})"))

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Cities seed/repair complete!"))
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.WARNING(f"Updated: {updated}"))
        self.stdout.write(self.style.SUCCESS(f"Auto-Approved: {approved_count}"))
        if missing_countries:
            self.stdout.write(self.style.WARNING(f"Countries missing (skipped): {missing_countries}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors: {errors}"))
        self.stdout.write(self.style.SUCCESS(f"All imports marked as approved by: {approver.username}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
