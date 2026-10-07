from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from locations.models import Country, Region
from approval_system.models import ApprovalStatus

User = get_user_model()

class Command(BaseCommand):
    """
    Seed/repair Regions for already-loaded countries.

    What it does:
      1) For ALL countries (optionally filtered by continent), ensures a baseline Region called
         "National" exists when the country has zero regions (default behavior).
      2) For specific countries, seeds real first-level administrative regions (states/provinces),
         using a deterministic, offline, idempotent dataset.

    Design goals:
      - Safe on a fresh database
      - Safe to re-run as a repair tool (idempotent)
      - Offline / no external dependencies
      - Does NOT delete anything

    Countries with detailed regions included (by request):
      - US (states + DC)
      - Mexico (states + Mexico City)
      - Costa Rica (provinces)
      - Germany (Bundesländer)
      - Austria (Bundesländer)

    Notes:
      - Region uniqueness is (country, name) in your model, so update_or_create is safe.
      - Region.code is optional; we set commonly-used codes where available.
    """

    help = "Seed/repair Regions (baseline National + detailed regions for selected countries)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only create the baseline 'National' region if the country currently has zero regions (default behavior).",
        )
        parser.add_argument(
            "--ensure-national",
            action="store_true",
            help="Ensure every country has a 'National' region even if other regions exist.",
        )
        parser.add_argument(
            "--include-continents",
            nargs="*",
            default=None,
            help="Optional list of continents to include (must match Country.continent choices). Example: --include-continents Europe Asia",
        )
        parser.add_argument(
            "--skip-detailed",
            action="store_true",
            help="Skip seeding detailed regions for the selected countries (US/MX/CR/DE/AT).",
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
        only_missing = options.get("only_missing", False)
        ensure_national = options.get("ensure_national", False)
        continents = options.get("include_continents")
        skip_detailed = options.get("skip_detailed", False)

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

        # Default behavior: only create National when a country has zero regions
        if not ensure_national:
            only_missing = True

        allowed_continents = {c[0] for c in Country._meta.get_field("continent").choices}

        qs = Country.objects.all()
        if continents:
            # Validate supplied continents to prevent silent no-ops
            invalid = sorted(set(continents) - allowed_continents)
            if invalid:
                self.stdout.write(self.style.ERROR(
                    f"Invalid continent(s): {', '.join(invalid)}. Allowed: {', '.join(sorted(allowed_continents))}"
                ))
                return
            qs = qs.filter(continent__in=continents)

        created = 0
        updated = 0
        skipped = 0
        approved_count = 0 
        errors = 0

        # -------------------------
        # Baseline: National region
        # -------------------------
        for country in qs.order_by("continent", "name"):
            try:
                has_any = country.regions.exists()
                if only_missing and has_any:
                    skipped += 1
                    continue

                region, was_created = Region.objects.update_or_create(
                    country=country,
                    name="National",
                    defaults={
                        "code": country.iso_code,
                        "description": "Baseline region (auto-created). Replace/add real states/provinces as needed.",
                    },
                )

                # Set approval fields for both new and existing regions
                needs_save = False
                if region.approval_status != ApprovalStatus.APPROVED:
                    region.approval_status = ApprovalStatus.APPROVED
                    needs_save = True
                if not region.submitted_by:
                    region.submitted_by = approver
                    region.submitted_at = timezone.now()
                    needs_save = True
                if not region.reviewed_by:
                    region.reviewed_by = approver
                    region.reviewed_at = timezone.now()
                    needs_save = True
                    
                if needs_save:
                    region.save()
                    approved_count += 1

                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"✓ Created & Approved: National ({country.iso_code})"))
                else:
                    updated += 1
                    self.stdout.write(self.style.WARNING(f"↻ Updated: National ({country.iso_code})"))

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"✗ Error for {country.name} ({country.iso_code}): {e}"))

        # -------------------------
        # Detailed regions for selected countries
        # -------------------------
        if not skip_detailed:
            detailed = {
                # United States: 50 states + DC
                "US": [
                    ("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"), ("Arkansas", "AR"),
                    ("California", "CA"), ("Colorado", "CO"), ("Connecticut", "CT"), ("Delaware", "DE"),
                    ("Florida", "FL"), ("Georgia", "GA"), ("Hawaii", "HI"), ("Idaho", "ID"),
                    ("Illinois", "IL"), ("Indiana", "IN"), ("Iowa", "IA"), ("Kansas", "KS"),
                    ("Kentucky", "KY"), ("Louisiana", "LA"), ("Maine", "ME"), ("Maryland", "MD"),
                    ("Massachusetts", "MA"), ("Michigan", "MI"), ("Minnesota", "MN"), ("Mississippi", "MS"),
                    ("Missouri", "MO"), ("Montana", "MT"), ("Nebraska", "NE"), ("Nevada", "NV"),
                    ("New Hampshire", "NH"), ("New Jersey", "NJ"), ("New Mexico", "NM"), ("New York", "NY"),
                    ("North Carolina", "NC"), ("North Dakota", "ND"), ("Ohio", "OH"), ("Oklahoma", "OK"),
                    ("Oregon", "OR"), ("Pennsylvania", "PA"), ("Rhode Island", "RI"), ("South Carolina", "SC"),
                    ("South Dakota", "SD"), ("Tennessee", "TN"), ("Texas", "TX"), ("Utah", "UT"),
                    ("Vermont", "VT"), ("Virginia", "VA"), ("Washington", "WA"), ("West Virginia", "WV"),
                    ("Wisconsin", "WI"), ("Wyoming", "WY"),
                    ("District of Columbia", "DC"), ("US Virgin Islands", "VI"),
                ],

                # Mexico: 31 states + Mexico City (CDMX)
                "MX": [
                    ("Aguascalientes", "AGU"), ("Baja California", "BCN"), ("Baja California Sur", "BCS"),
                    ("Campeche", "CAM"), ("Chiapas", "CHP"), ("Chihuahua", "CHH"), ("Coahuila", "COA"),
                    ("Colima", "COL"), ("Durango", "DUR"), ("Guanajuato", "GUA"), ("Guerrero", "GRO"),
                    ("Hidalgo", "HID"), ("Jalisco", "JAL"), ("México", "MEX"), ("Michoacán", "MIC"),
                    ("Morelos", "MOR"), ("Nayarit", "NAY"), ("Nuevo León", "NLE"), ("Oaxaca", "OAX"),
                    ("Puebla", "PUE"), ("Querétaro", "QUE"), ("Quintana Roo", "ROO"), ("San Luis Potosí", "SLP"),
                    ("Sinaloa", "SIN"), ("Sonora", "SON"), ("Tabasco", "TAB"), ("Tamaulipas", "TAM"),
                    ("Tlaxcala", "TLA"), ("Veracruz", "VER"), ("Yucatán", "YUC"), ("Zacatecas", "ZAC"),
                    ("Mexico City", "CMX"),
                ],

                # Costa Rica: 7 provinces
                "CR": [
                    ("San José", "SJ"), ("Alajuela", "A"), ("Cartago", "C"), ("Heredia", "H"),
                    ("Guanacaste", "G"), ("Puntarenas", "P"), ("Limón", "L"),
                ],

                # Germany: 16 Bundesländer
                "DE": [
                    ("Baden-Württemberg", "BW"), ("Bavaria", "BY"), ("Berlin", "BE"), ("Brandenburg", "BB"),
                    ("Bremen", "HB"), ("Hamburg", "HH"), ("Hesse", "HE"), ("Lower Saxony", "NI"),
                    ("Mecklenburg-Vorpommern", "MV"), ("North Rhine-Westphalia", "NW"), ("Rhineland-Palatinate", "RP"),
                    ("Saarland", "SL"), ("Saxony", "SN"), ("Saxony-Anhalt", "ST"), ("Schleswig-Holstein", "SH"),
                    ("Thuringia", "TH"),
                ],

                # Austria: 9 Bundesländer
                "AT": [
                    ("Burgenland", "B"), ("Carinthia", "K"), ("Lower Austria", "N"), ("Upper Austria", "O"),
                    ("Salzburg", "S"), ("Styria", "ST"), ("Tyrol", "T"), ("Vorarlberg", "V"), ("Vienna", "W"),
                ],
            }

            self.stdout.write(self.style.SUCCESS("\n" + "-" * 60))
            self.stdout.write(self.style.SUCCESS("Seeding detailed regions for US/MX/CR/DE/AT..."))

            det_created = 0
            det_updated = 0
            det_skipped_missing_country = 0
            det_errors = 0
            det_approved = 0

            for iso, regions in detailed.items():
                try:
                    country = Country.objects.get(iso_code=iso)
                except Country.DoesNotExist:
                    det_skipped_missing_country += 1
                    self.stdout.write(self.style.WARNING(f"⚠ Country not found: {iso} (skipping detailed regions)"))
                    continue

                for name, code in regions:
                    try:
                        region, was_created = Region.objects.update_or_create(
                            country=country,
                            name=name,
                            defaults={
                                "code": code,
                                "description": f"Seeded administrative region for {country.name}.",
                                # Approval fields - mark as approved for system imports
                                "approval_status": ApprovalStatus.APPROVED,
                                "submitted_by": approver,
                                "submitted_at": timezone.now(),
                                "reviewed_by": approver,
                                "reviewed_at": timezone.now(),
                            },
                        )
                        
                        if was_created:
                            det_created += 1
                            det_approved += 1
                        else:
                            det_updated += 1
                            # Ensure existing region is approved
                            if region.approval_status != ApprovalStatus.APPROVED:
                                region.approval_status = ApprovalStatus.APPROVED
                                region.reviewed_by = approver
                                region.reviewed_at = timezone.now()
                                region.save()
                                det_approved += 1
                                
                    except Exception as e:
                        det_errors += 1
                        self.stdout.write(self.style.ERROR(
                            f"✗ Error seeding region '{name}' for {iso}: {e}"
                        ))

                self.stdout.write(self.style.SUCCESS(f"✓ Done: {country.name} ({iso})"))

            self.stdout.write(self.style.SUCCESS("\nDetailed regions complete."))
            self.stdout.write(self.style.SUCCESS(f"Created: {det_created}"))
            self.stdout.write(self.style.WARNING(f"Updated: {det_updated}"))
            self.stdout.write(self.style.SUCCESS(f"Auto-Approved: {det_approved}"))
            if det_skipped_missing_country:
                self.stdout.write(self.style.WARNING(f"Countries missing (skipped): {det_skipped_missing_country}"))
            if det_errors:
                self.stdout.write(self.style.ERROR(f"Errors: {det_errors}"))
            self.stdout.write(self.style.SUCCESS("-" * 60))

        # -------------------------
        # Summary
        # -------------------------
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Regions seed/repair complete!"))
        self.stdout.write(self.style.SUCCESS(f"Baseline National created: {created}"))
        self.stdout.write(self.style.WARNING(f"Baseline National updated: {updated}"))
        self.stdout.write(self.style.WARNING(f"Baseline National skipped: {skipped}"))
        self.stdout.write(self.style.SUCCESS(f"Total Auto-Approved: {approved_count}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"Baseline National errors: {errors}"))
        self.stdout.write(self.style.SUCCESS(f"All imports marked as approved by: {approver.username}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))