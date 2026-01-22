from django.core.management.base import BaseCommand
from locations.models import Country


class Command(BaseCommand):
    """
    Seed/repair Countries (sovereign states only) for:
      - Europe
      - Asia
      - North America
      - South America

    Design goals:
      - Safe on a fresh database
      - Safe to re-run as a repair tool (idempotent)
      - No network calls, no external dependencies
      - Does NOT delete anything
    """

    help = "Seed/repair Countries (ISO-3166-1, sovereign-only) for Europe/Asia/North America/South America"

    def handle(self, *args, **options):
        # Format: (name, iso2, iso3, continent)
        # Continent must match Country.Continent choices in your model.
        countries = [
            # -------------------------
            # North America (sovereign states)
            # -------------------------
            ("Antigua and Barbuda", "AG", "ATG", "North America"),
            ("Bahamas", "BS", "BHS", "North America"),
            ("Barbados", "BB", "BRB", "North America"),
            ("Belize", "BZ", "BLZ", "North America"),
            ("Canada", "CA", "CAN", "North America"),
            ("Costa Rica", "CR", "CRI", "North America"),
            ("Cuba", "CU", "CUB", "North America"),
            ("Dominica", "DM", "DMA", "North America"),
            ("Dominican Republic", "DO", "DOM", "North America"),
            ("El Salvador", "SV", "SLV", "North America"),
            ("Grenada", "GD", "GRD", "North America"),
            ("Guatemala", "GT", "GTM", "North America"),
            ("Haiti", "HT", "HTI", "North America"),
            ("Honduras", "HN", "HND", "North America"),
            ("Jamaica", "JM", "JAM", "North America"),
            ("Mexico", "MX", "MEX", "North America"),
            ("Nicaragua", "NI", "NIC", "North America"),
            ("Panama", "PA", "PAN", "North America"),
            ("Saint Kitts and Nevis", "KN", "KNA", "North America"),
            ("Saint Lucia", "LC", "LCA", "North America"),
            ("Saint Vincent and the Grenadines", "VC", "VCT", "North America"),
            ("Trinidad and Tobago", "TT", "TTO", "North America"),
            ("United States", "US", "USA", "North America"),

            # -------------------------
            # South America (sovereign states)
            # -------------------------
            ("Argentina", "AR", "ARG", "South America"),
            ("Bolivia", "BO", "BOL", "South America"),
            ("Brazil", "BR", "BRA", "South America"),
            ("Chile", "CL", "CHL", "South America"),
            ("Colombia", "CO", "COL", "South America"),
            ("Ecuador", "EC", "ECU", "South America"),
            ("Guyana", "GY", "GUY", "South America"),
            ("Paraguay", "PY", "PRY", "South America"),
            ("Peru", "PE", "PER", "South America"),
            ("Suriname", "SR", "SUR", "South America"),
            ("Uruguay", "UY", "URY", "South America"),
            ("Venezuela", "VE", "VEN", "South America"),

            # -------------------------
            # Europe (sovereign states)
            # -------------------------
            ("Albania", "AL", "ALB", "Europe"),
            ("Andorra", "AD", "AND", "Europe"),
            ("Austria", "AT", "AUT", "Europe"),
            ("Belarus", "BY", "BLR", "Europe"),
            ("Belgium", "BE", "BEL", "Europe"),
            ("Bosnia and Herzegovina", "BA", "BIH", "Europe"),
            ("Bulgaria", "BG", "BGR", "Europe"),
            ("Croatia", "HR", "HRV", "Europe"),
            ("Cyprus", "CY", "CYP", "Europe"),
            ("Czechia", "CZ", "CZE", "Europe"),
            ("Denmark", "DK", "DNK", "Europe"),
            ("Estonia", "EE", "EST", "Europe"),
            ("Finland", "FI", "FIN", "Europe"),
            ("France", "FR", "FRA", "Europe"),
            ("Germany", "DE", "DEU", "Europe"),
            ("Greece", "GR", "GRC", "Europe"),
            ("Hungary", "HU", "HUN", "Europe"),
            ("Iceland", "IS", "ISL", "Europe"),
            ("Ireland", "IE", "IRL", "Europe"),
            ("Italy", "IT", "ITA", "Europe"),
            ("Latvia", "LV", "LVA", "Europe"),
            ("Liechtenstein", "LI", "LIE", "Europe"),
            ("Lithuania", "LT", "LTU", "Europe"),
            ("Luxembourg", "LU", "LUX", "Europe"),
            ("Malta", "MT", "MLT", "Europe"),
            ("Moldova", "MD", "MDA", "Europe"),
            ("Monaco", "MC", "MCO", "Europe"),
            ("Montenegro", "ME", "MNE", "Europe"),
            ("Netherlands", "NL", "NLD", "Europe"),
            ("North Macedonia", "MK", "MKD", "Europe"),
            ("Norway", "NO", "NOR", "Europe"),
            ("Poland", "PL", "POL", "Europe"),
            ("Portugal", "PT", "PRT", "Europe"),
            ("Romania", "RO", "ROU", "Europe"),
            ("Russia", "RU", "RUS", "Europe"),
            ("San Marino", "SM", "SMR", "Europe"),
            ("Serbia", "RS", "SRB", "Europe"),
            ("Slovakia", "SK", "SVK", "Europe"),
            ("Slovenia", "SI", "SVN", "Europe"),
            ("Spain", "ES", "ESP", "Europe"),
            ("Sweden", "SE", "SWE", "Europe"),
            ("Switzerland", "CH", "CHE", "Europe"),
            ("Ukraine", "UA", "UKR", "Europe"),
            ("United Kingdom", "GB", "GBR", "Europe"),
            ("Vatican City", "VA", "VAT", "Europe"),

            # -------------------------
            # Asia (sovereign states / widely used ISO entries)
            # -------------------------
            ("Afghanistan", "AF", "AFG", "Asia"),
            ("Armenia", "AM", "ARM", "Asia"),
            ("Azerbaijan", "AZ", "AZE", "Asia"),
            ("Bahrain", "BH", "BHR", "Asia"),
            ("Bangladesh", "BD", "BGD", "Asia"),
            ("Bhutan", "BT", "BTN", "Asia"),
            ("Brunei", "BN", "BRN", "Asia"),
            ("Cambodia", "KH", "KHM", "Asia"),
            ("China", "CN", "CHN", "Asia"),
            ("Georgia", "GE", "GEO", "Asia"),
            ("India", "IN", "IND", "Asia"),
            ("Indonesia", "ID", "IDN", "Asia"),
            ("Iran", "IR", "IRN", "Asia"),
            ("Iraq", "IQ", "IRQ", "Asia"),
            ("Israel", "IL", "ISR", "Asia"),
            ("Japan", "JP", "JPN", "Asia"),
            ("Jordan", "JO", "JOR", "Asia"),
            ("Kazakhstan", "KZ", "KAZ", "Asia"),
            ("Kuwait", "KW", "KWT", "Asia"),
            ("Kyrgyzstan", "KG", "KGZ", "Asia"),
            ("Laos", "LA", "LAO", "Asia"),
            ("Lebanon", "LB", "LBN", "Asia"),
            ("Malaysia", "MY", "MYS", "Asia"),
            ("Maldives", "MV", "MDV", "Asia"),
            ("Mongolia", "MN", "MNG", "Asia"),
            ("Myanmar", "MM", "MMR", "Asia"),
            ("Nepal", "NP", "NPL", "Asia"),
            ("North Korea", "KP", "PRK", "Asia"),
            ("Oman", "OM", "OMN", "Asia"),
            ("Pakistan", "PK", "PAK", "Asia"),
            ("Philippines", "PH", "PHL", "Asia"),
            ("Qatar", "QA", "QAT", "Asia"),
            ("Saudi Arabia", "SA", "SAU", "Asia"),
            ("Singapore", "SG", "SGP", "Asia"),
            ("South Korea", "KR", "KOR", "Asia"),
            ("Sri Lanka", "LK", "LKA", "Asia"),
            ("Syria", "SY", "SYR", "Asia"),
            ("Taiwan", "TW", "TWN", "Asia"),
            ("Tajikistan", "TJ", "TJK", "Asia"),
            ("Thailand", "TH", "THA", "Asia"),
            ("Timor-Leste", "TL", "TLS", "Asia"),
            ("Turkey", "TR", "TUR", "Asia"),
            ("Turkmenistan", "TM", "TKM", "Asia"),
            ("United Arab Emirates", "AE", "ARE", "Asia"),
            ("Uzbekistan", "UZ", "UZB", "Asia"),
            ("Vietnam", "VN", "VNM", "Asia"),
            ("Yemen", "YE", "YEM", "Asia"),
            ("Palestine", "PS", "PSE", "Asia"),
        ]

        created = 0
        updated = 0
        errors = 0

        allowed_continents = {c[0] for c in Country._meta.get_field("continent").choices}

        for name, iso2, iso3, continent in countries:
            try:
                if continent not in allowed_continents:
                    self.stdout.write(self.style.ERROR(
                        f"✗ Invalid continent '{continent}' for {name} ({iso2}/{iso3})"
                    ))
                    errors += 1
                    continue

                _, was_created = Country.objects.update_or_create(
                    iso_code=iso2,
                    defaults={
                        "name": name,
                        "iso3_code": iso3,
                        "continent": continent,
                    }
                )

                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"✓ Created: {name} ({iso2})"))
                else:
                    updated += 1
                    self.stdout.write(self.style.WARNING(f"↻ Updated: {name} ({iso2})"))

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"✗ Error importing {name} ({iso2}): {e}"))

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Countries seed/repair complete!")) 
        self.stdout.write(self.style.SUCCESS(f"Created: {created}")) 
        self.stdout.write(self.style.WARNING(f"Updated: {updated}")) 
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors: {errors}")) 
        self.stdout.write(self.style.SUCCESS("=" * 60))
