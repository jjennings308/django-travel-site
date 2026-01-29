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
            # North America
            # -------------------------
            ("Antigua and Barbuda", "AG", "ATG", "North America", "+1-268", "XCD", "East Caribbean Dollar", "ag"),
            ("Bahamas", "BS", "BHS", "North America", "+1-242", "BSD", "Bahamian Dollar", "bs"),
            ("Barbados", "BB", "BRB", "North America", "+1-246", "BBD", "Barbadian Dollar", "bb"),
            ("Belize", "BZ", "BLZ", "North America", "+501", "BZD", "Belize Dollar", "bz"),
            ("Canada", "CA", "CAN", "North America", "+1", "CAD", "Canadian Dollar", "ca"),
            ("Costa Rica", "CR", "CRI", "North America", "+506", "CRC", "Costa Rican Colón", "cr"),
            ("Cuba", "CU", "CUB", "North America", "+53", "CUP", "Cuban Peso", "cu"),
            ("Dominica", "DM", "DMA", "North America", "+1-767", "XCD", "East Caribbean Dollar", "dm"),
            ("Dominican Republic", "DO", "DOM", "North America", "+1-809", "DOP", "Dominican Peso", "do"),
            ("El Salvador", "SV", "SLV", "North America", "+503", "USD", "US Dollar", "sv"),
            ("Grenada", "GD", "GRD", "North America", "+1-473", "XCD", "East Caribbean Dollar", "gd"),
            ("Guatemala", "GT", "GTM", "North America", "+502", "GTQ", "Guatemalan Quetzal", "gt"),
            ("Haiti", "HT", "HTI", "North America", "+509", "HTG", "Haitian Gourde", "ht"),
            ("Honduras", "HN", "HND", "North America", "+504", "HNL", "Honduran Lempira", "hn"),
            ("Jamaica", "JM", "JAM", "North America", "+1-876", "JMD", "Jamaican Dollar", "jm"),
            ("Mexico", "MX", "MEX", "North America", "+52", "MXN", "Mexican Peso", "mx"),
            ("Nicaragua", "NI", "NIC", "North America", "+505", "NIO", "Nicaraguan Córdoba", "ni"),
            ("Panama", "PA", "PAN", "North America", "+507", "PAB", "Panamanian Balboa", "pa"),
            ("Saint Kitts and Nevis", "KN", "KNA", "North America", "+1-869", "XCD", "East Caribbean Dollar", "kn"),
            ("Saint Lucia", "LC", "LCA", "North America", "+1-758", "XCD", "East Caribbean Dollar", "lc"),
            ("Saint Vincent and the Grenadines", "VC", "VCT", "North America", "+1-784", "XCD", "East Caribbean Dollar", "vc"),
            ("Trinidad and Tobago", "TT", "TTO", "North America", "+1-868", "TTD", "Trinidad and Tobago Dollar", "tt"),
            ("United States", "US", "USA", "North America", "+1", "USD", "US Dollar", "us"),

            # -------------------------
            # South America
            # -------------------------
            ("Argentina", "AR", "ARG", "South America", "+54", "ARS", "Argentine Peso", "ar"),
            ("Bolivia", "BO", "BOL", "South America", "+591", "BOB", "Bolivian Boliviano", "bo"),
            ("Brazil", "BR", "BRA", "South America", "+55", "BRL", "Brazilian Real", "br"),
            ("Chile", "CL", "CHL", "South America", "+56", "CLP", "Chilean Peso", "cl"),
            ("Colombia", "CO", "COL", "South America", "+57", "COP", "Colombian Peso", "co"),
            ("Ecuador", "EC", "ECU", "South America", "+593", "USD", "US Dollar", "ec"),
            ("Guyana", "GY", "GUY", "South America", "+592", "GYD", "Guyanese Dollar", "gy"),
            ("Paraguay", "PY", "PRY", "South America", "+595", "PYG", "Paraguayan Guaraní", "py"),
            ("Peru", "PE", "PER", "South America", "+51", "PEN", "Peruvian Sol", "pe"),
            ("Suriname", "SR", "SUR", "South America", "+597", "SRD", "Surinamese Dollar", "sr"),
            ("Uruguay", "UY", "URY", "South America", "+598", "UYU", "Uruguayan Peso", "uy"),
            ("Venezuela", "VE", "VEN", "South America", "+58", "VES", "Venezuelan Bolívar Soberano", "ve"),

            # -------------------------
            # Europe
            # -------------------------
            ("Albania", "AL", "ALB", "Europe", "+355", "ALL", "Albanian Lek", "al"),
            ("Andorra", "AD", "AND", "Europe", "+376", "EUR", "Euro", "ad"),
            ("Austria", "AT", "AUT", "Europe", "+43", "EUR", "Euro", "at"),
            ("Belarus", "BY", "BLR", "Europe", "+375", "BYN", "Belarusian Ruble", "by"),
            ("Belgium", "BE", "BEL", "Europe", "+32", "EUR", "Euro", "be"),
            ("Bosnia and Herzegovina", "BA", "BIH", "Europe", "+387", "BAM", "Bosnia-Herzegovina Convertible Mark", "ba"),
            ("Bulgaria", "BG", "BGR", "Europe", "+359", "BGN", "Bulgarian Lev", "bg"),
            ("Croatia", "HR", "HRV", "Europe", "+385", "EUR", "Euro", "hr"),
            ("Cyprus", "CY", "CYP", "Europe", "+357", "EUR", "Euro", "cy"),
            ("Czechia", "CZ", "CZE", "Europe", "+420", "CZK", "Czech Koruna", "cz"),
            ("Denmark", "DK", "DNK", "Europe", "+45", "DKK", "Danish Krone", "dk"),
            ("Estonia", "EE", "EST", "Europe", "+372", "EUR", "Euro", "ee"),
            ("Finland", "FI", "FIN", "Europe", "+358", "EUR", "Euro", "fi"),
            ("France", "FR", "FRA", "Europe", "+33", "EUR", "Euro", "fr"),
            ("Germany", "DE", "DEU", "Europe", "+49", "EUR", "Euro", "de"),
            ("Greece", "GR", "GRC", "Europe", "+30", "EUR", "Euro", "gr"),
            ("Hungary", "HU", "HUN", "Europe", "+36", "HUF", "Hungarian Forint", "hu"),
            ("Iceland", "IS", "ISL", "Europe", "+354", "ISK", "Icelandic Króna", "is"),
            ("Ireland", "IE", "IRL", "Europe", "+353", "EUR", "Euro", "ie"),
            ("Italy", "IT", "ITA", "Europe", "+39", "EUR", "Euro", "it"),
            ("Latvia", "LV", "LVA", "Europe", "+371", "EUR", "Euro", "lv"),
            ("Liechtenstein", "LI", "LIE", "Europe", "+423", "CHF", "Swiss Franc", "li"),
            ("Lithuania", "LT", "LTU", "Europe", "+370", "EUR", "Euro", "lt"),
            ("Luxembourg", "LU", "LUX", "Europe", "+352", "EUR", "Euro", "lu"),
            ("Malta", "MT", "MLT", "Europe", "+356", "EUR", "Euro", "mt"),
            ("Moldova", "MD", "MDA", "Europe", "+373", "MDL", "Moldovan Leu", "md"),
            ("Monaco", "MC", "MCO", "Europe", "+377", "EUR", "Euro", "mc"),
            ("Montenegro", "ME", "MNE", "Europe", "+382", "EUR", "Euro", "me"),
            ("Netherlands", "NL", "NLD", "Europe", "+31", "EUR", "Euro", "nl"),
            ("North Macedonia", "MK", "MKD", "Europe", "+389", "MKD", "Macedonian Denar", "mk"),
            ("Norway", "NO", "NOR", "Europe", "+47", "NOK", "Norwegian Krone", "no"),
            ("Poland", "PL", "POL", "Europe", "+48", "PLN", "Polish Złoty", "pl"),
            ("Portugal", "PT", "PRT", "Europe", "+351", "EUR", "Euro", "pt"),
            ("Romania", "RO", "ROU", "Europe", "+40", "RON", "Romanian Leu", "ro"),
            ("Russia", "RU", "RUS", "Europe", "+7", "RUB", "Russian Ruble", "ru"),
            ("San Marino", "SM", "SMR", "Europe", "+378", "EUR", "Euro", "sm"),
            ("Serbia", "RS", "SRB", "Europe", "+381", "RSD", "Serbian Dinar", "rs"),
            ("Slovakia", "SK", "SVK", "Europe", "+421", "EUR", "Euro", "sk"),
            ("Slovenia", "SI", "SVN", "Europe", "+386", "EUR", "Euro", "si"),
            ("Spain", "ES", "ESP", "Europe", "+34", "EUR", "Euro", "es"),
            ("Sweden", "SE", "SWE", "Europe", "+46", "SEK", "Swedish Krona", "se"),
            ("Switzerland", "CH", "CHE", "Europe", "+41", "CHF", "Swiss Franc", "ch"),
            ("Ukraine", "UA", "UKR", "Europe", "+380", "UAH", "Ukrainian Hryvnia", "ua"),
            ("United Kingdom", "GB", "GBR", "Europe", "+44", "GBP", "British Pound", "gb"),
            ("Vatican City", "VA", "VAT", "Europe", "+39", "EUR", "Euro", "va"),

            # -------------------------
            # Asia
            # -------------------------
            ("Afghanistan", "AF", "AFG", "Asia", "+93", "AFN", "Afghan Afghani", "af"),
            ("Armenia", "AM", "ARM", "Asia", "+374", "AMD", "Armenian Dram", "am"),
            ("Azerbaijan", "AZ", "AZE", "Asia", "+994", "AZN", "Azerbaijani Manat", "az"),
            ("Bahrain", "BH", "BHR", "Asia", "+973", "BHD", "Bahraini Dinar", "bh"),
            ("Bangladesh", "BD", "BGD", "Asia", "+880", "BDT", "Bangladeshi Taka", "bd"),
            ("Bhutan", "BT", "BTN", "Asia", "+975", "BTN", "Bhutanese Ngultrum", "bt"),
            ("Brunei", "BN", "BRN", "Asia", "+673", "BND", "Brunei Dollar", "bn"),
            ("Cambodia", "KH", "KHM", "Asia", "+855", "KHR", "Cambodian Riel", "kh"),
            ("China", "CN", "CHN", "Asia", "+86", "CNY", "Chinese Yuan", "cn"),
            ("Georgia", "GE", "GEO", "Asia", "+995", "GEL", "Georgian Lari", "ge"),
            ("India", "IN", "IND", "Asia", "+91", "INR", "Indian Rupee", "in"),
            ("Indonesia", "ID", "IDN", "Asia", "+62", "IDR", "Indonesian Rupiah", "id"),
            ("Iran", "IR", "IRN", "Asia", "+98", "IRR", "Iranian Rial", "ir"),
            ("Iraq", "IQ", "IRQ", "Asia", "+964", "IQD", "Iraqi Dinar", "iq"),
            ("Israel", "IL", "ISR", "Asia", "+972", "ILS", "Israeli New Shekel", "il"),
            ("Japan", "JP", "JPN", "Asia", "+81", "JPY", "Japanese Yen", "jp"),
            ("Jordan", "JO", "JOR", "Asia", "+962", "JOD", "Jordanian Dinar", "jo"),
            ("Kazakhstan", "KZ", "KAZ", "Asia", "+7", "KZT", "Kazakhstani Tenge", "kz"),
            ("Kuwait", "KW", "KWT", "Asia", "+965", "KWD", "Kuwaiti Dinar", "kw"),
            ("Kyrgyzstan", "KG", "KGZ", "Asia", "+996", "KGS", "Kyrgyzstani Som", "kg"),
            ("Laos", "LA", "LAO", "Asia", "+856", "LAK", "Lao Kip", "la"),
            ("Lebanon", "LB", "LBN", "Asia", "+961", "LBP", "Lebanese Pound", "lb"),
            ("Malaysia", "MY", "MYS", "Asia", "+60", "MYR", "Malaysian Ringgit", "my"),
            ("Maldives", "MV", "MDV", "Asia", "+960", "MVR", "Maldivian Rufiyaa", "mv"),
            ("Mongolia", "MN", "MNG", "Asia", "+976", "MNT", "Mongolian Tögrög", "mn"),
            ("Myanmar", "MM", "MMR", "Asia", "+95", "MMK", "Myanmar Kyat", "mm"),
            ("Nepal", "NP", "NPL", "Asia", "+977", "NPR", "Nepalese Rupee", "np"),
            ("North Korea", "KP", "PRK", "Asia", "+850", "KPW", "North Korean Won", "kp"),
            ("Oman", "OM", "OMN", "Asia", "+968", "OMR", "Omani Rial", "om"),
            ("Pakistan", "PK", "PAK", "Asia", "+92", "PKR", "Pakistani Rupee", "pk"),
            ("Philippines", "PH", "PHL", "Asia", "+63", "PHP", "Philippine Peso", "ph"),
            ("Qatar", "QA", "QAT", "Asia", "+974", "QAR", "Qatari Riyal", "qa"),
            ("Saudi Arabia", "SA", "SAU", "Asia", "+966", "SAR", "Saudi Riyal", "sa"),
            ("Singapore", "SG", "SGP", "Asia", "+65", "SGD", "Singapore Dollar", "sg"),
            ("South Korea", "KR", "KOR", "Asia", "+82", "KRW", "South Korean Won", "kr"),
            ("Sri Lanka", "LK", "LKA", "Asia", "+94", "LKR", "Sri Lankan Rupee", "lk"),
            ("Syria", "SY", "SYR", "Asia", "+963", "SYP", "Syrian Pound", "sy"),
            ("Taiwan", "TW", "TWN", "Asia", "+886", "TWD", "New Taiwan Dollar", "tw"),
            ("Tajikistan", "TJ", "TJK", "Asia", "+992", "TJS", "Tajikistani Somoni", "tj"),
            ("Thailand", "TH", "THA", "Asia", "+66", "THB", "Thai Baht", "th"),
            ("Timor-Leste", "TL", "TLS", "Asia", "+670", "USD", "US Dollar", "tl"),
            ("Turkey", "TR", "TUR", "Asia", "+90", "TRY", "Turkish Lira", "tr"),
            ("Turkmenistan", "TM", "TKM", "Asia", "+993", "TMT", "Turkmenistan Manat", "tm"),
            ("United Arab Emirates", "AE", "ARE", "Asia", "+971", "AED", "UAE Dirham", "ae"),
            ("Uzbekistan", "UZ", "UZB", "Asia", "+998", "UZS", "Uzbekistani Som", "uz"),
            ("Vietnam", "VN", "VNM", "Asia", "+84", "VND", "Vietnamese Đồng", "vn"),
            ("Yemen", "YE", "YEM", "Asia", "+967", "YER", "Yemeni Rial", "ye"),
            ("Palestine", "PS", "PSE", "Asia", "+970", "ILS", "Israeli New Shekel", "ps"),

            # -------------------------
            # Africa
            # -------------------------
            ("Algeria", "DZ", "DZA", "Africa", "+213", "DZD", "Algerian Dinar", "dz"),
            ("Angola", "AO", "AGO", "Africa", "+244", "AOA", "Angolan Kwanza", "ao"),
            ("Benin", "BJ", "BEN", "Africa", "+229", "XOF", "CFA Franc BCEAO", "bj"),
            ("Botswana", "BW", "BWA", "Africa", "+267", "BWP", "Botswana Pula", "bw"),
            ("Burkina Faso", "BF", "BFA", "Africa", "+226", "XOF", "CFA Franc BCEAO", "bf"),
            ("Burundi", "BI", "BDI", "Africa", "+257", "BIF", "Burundian Franc", "bi"),
            ("Cabo Verde", "CV", "CPV", "Africa", "+238", "CVE", "Cape Verdean Escudo", "cv"),
            ("Cameroon", "CM", "CMR", "Africa", "+237", "XAF", "CFA Franc BEAC", "cm"),
            ("Central African Republic", "CF", "CAF", "Africa", "+236", "XAF", "CFA Franc BEAC", "cf"),
            ("Chad", "TD", "TCD", "Africa", "+235", "XAF", "CFA Franc BEAC", "td"),
            ("Comoros", "KM", "COM", "Africa", "+269", "KMF", "Comorian Franc", "km"),
            ("Congo (Congo-Brazzaville)", "CG", "COG", "Africa", "+242", "XAF", "CFA Franc BEAC", "cg"),
            ("Congo (Democratic Republic)", "CD", "COD", "Africa", "+243", "CDF", "Congolese Franc", "cd"),
            ("Djibouti", "DJ", "DJI", "Africa", "+253", "DJF", "Djiboutian Franc", "dj"),
            ("Egypt", "EG", "EGY", "Africa", "+20", "EGP", "Egyptian Pound", "eg"),
            ("Equatorial Guinea", "GQ", "GNQ", "Africa", "+240", "XAF", "CFA Franc BEAC", "gq"),
            ("Eritrea", "ER", "ERI", "Africa", "+291", "ERN", "Eritrean Nakfa", "er"),
            ("Eswatini", "SZ", "SWZ", "Africa", "+268", "SZL", "Swazi Lilangeni", "sz"),
            ("Ethiopia", "ET", "ETH", "Africa", "+251", "ETB", "Ethiopian Birr", "et"),
            ("Gabon", "GA", "GAB", "Africa", "+241", "XAF", "CFA Franc BEAC", "ga"),
            ("Gambia", "GM", "GMB", "Africa", "+220", "GMD", "Gambian Dalasi", "gm"),
            ("Ghana", "GH", "GHA", "Africa", "+233", "GHS", "Ghanaian Cedi", "gh"),
            ("Guinea", "GN", "GIN", "Africa", "+224", "GNF", "Guinean Franc", "gn"),
            ("Guinea-Bissau", "GW", "GNB", "Africa", "+245", "XOF", "CFA Franc BCEAO", "gw"),
            ("Ivory Coast", "CI", "CIV", "Africa", "+225", "XOF", "CFA Franc BCEAO", "ci"),
            ("Kenya", "KE", "KEN", "Africa", "+254", "KES", "Kenyan Shilling", "ke"),
            ("Lesotho", "LS", "LSO", "Africa", "+266", "LSL", "Lesotho Loti", "ls"),
            ("Liberia", "LR", "LBR", "Africa", "+231", "LRD", "Liberian Dollar", "lr"),
            ("Libya", "LY", "LBY", "Africa", "+218", "LYD", "Libyan Dinar", "ly"),
            ("Madagascar", "MG", "MDG", "Africa", "+261", "MGA", "Malagasy Ariary", "mg"),
            ("Malawi", "MW", "MWI", "Africa", "+265", "MWK", "Malawian Kwacha", "mw"),
            ("Mali", "ML", "MLI", "Africa", "+223", "XOF", "CFA Franc BCEAO", "ml"),
            ("Mauritania", "MR", "MRT", "Africa", "+222", "MRU", "Mauritanian Ouguiya", "mr"),
            ("Mauritius", "MU", "MUS", "Africa", "+230", "MUR", "Mauritian Rupee", "mu"),
            ("Morocco", "MA", "MAR", "Africa", "+212", "MAD", "Moroccan Dirham", "ma"),
            ("Mozambique", "MZ", "MOZ", "Africa", "+258", "MZN", "Mozambican Metical", "mz"),
            ("Namibia", "NA", "NAM", "Africa", "+264", "NAD", "Namibian Dollar", "na"),
            ("Niger", "NE", "NER", "Africa", "+227", "XOF", "CFA Franc BCEAO", "ne"),
            ("Nigeria", "NG", "NGA", "Africa", "+234", "NGN", "Nigerian Naira", "ng"),
            ("Rwanda", "RW", "RWA", "Africa", "+250", "RWF", "Rwandan Franc", "rw"),
            ("Sao Tome and Principe", "ST", "STP", "Africa", "+239", "STN", "São Tomé and Príncipe Dobra", "st"),
            ("Senegal", "SN", "SEN", "Africa", "+221", "XOF", "CFA Franc BCEAO", "sn"),
            ("Seychelles", "SC", "SYC", "Africa", "+248", "SCR", "Seychellois Rupee", "sc"),
            ("Sierra Leone", "SL", "SLE", "Africa", "+232", "SLE", "Sierra Leonean Leone", "sl"),
            ("Somalia", "SO", "SOM", "Africa", "+252", "SOS", "Somali Shilling", "so"),
            ("South Africa", "ZA", "ZAF", "Africa", "+27", "ZAR", "South African Rand", "za"),
            ("South Sudan", "SS", "SSD", "Africa", "+211", "SSP", "South Sudanese Pound", "ss"),
            ("Sudan", "SD", "SDN", "Africa", "+249", "SDG", "Sudanese Pound", "sd"),
            ("Tanzania", "TZ", "TZA", "Africa", "+255", "TZS", "Tanzanian Shilling", "tz"),
            ("Togo", "TG", "TGO", "Africa", "+228", "XOF", "CFA Franc BCEAO", "tg"),
            ("Tunisia", "TN", "TUN", "Africa", "+216", "TND", "Tunisian Dinar", "tn"),
            ("Uganda", "UG", "UGA", "Africa", "+256", "UGX", "Ugandan Shilling", "ug"),
            ("Zambia", "ZM", "ZMB", "Africa", "+260", "ZMW", "Zambian Kwacha", "zm"),
            ("Zimbabwe", "ZW", "ZWE", "Africa", "+263", "ZWL", "Zimbabwean Dollar", "zw"),

            # -------------------------
            # Oceania
            # -------------------------
            ("Australia", "AU", "AUS", "Oceania", "+61", "AUD", "Australian Dollar", "au"),
            ("Fiji", "FJ", "FJI", "Oceania", "+679", "FJD", "Fijian Dollar", "fj"),
            ("Kiribati", "KI", "KIR", "Oceania", "+686", "AUD", "Australian Dollar", "ki"),
            ("Marshall Islands", "MH", "MHL", "Oceania", "+692", "USD", "US Dollar", "mh"),
            ("Micronesia", "FM", "FSM", "Oceania", "+691", "USD", "US Dollar", "fm"),
            ("Nauru", "NR", "NRU", "Oceania", "+674", "AUD", "Australian Dollar", "nr"),
            ("New Zealand", "NZ", "NZL", "Oceania", "+64", "NZD", "New Zealand Dollar", "nz"),
            ("Palau", "PW", "PLW", "Oceania", "+680", "USD", "US Dollar", "pw"),
            ("Papua New Guinea", "PG", "PNG", "Oceania", "+675", "PGK", "Papua New Guinean Kina", "pg"),
            ("Samoa", "WS", "WSM", "Oceania", "+685", "WST", "Samoan Tālā", "ws"),
            ("Solomon Islands", "SB", "SLB", "Oceania", "+677", "SBD", "Solomon Islands Dollar", "sb"),
            ("Tonga", "TO", "TON", "Oceania", "+676", "TOP", "Tongan Paʻanga", "to"),
            ("Tuvalu", "TV", "TUV", "Oceania", "+688", "AUD", "Australian Dollar", "tv"),
            ("Vanuatu", "VU", "VUT", "Oceania", "+678", "VUV", "Vanuatu Vatu", "vu"),
        ]
        
        created = 0
        updated = 0
        errors = 0

        allowed_continents = {c[0] for c in Country._meta.get_field("continent").choices}

        for name, iso2, iso3, continent, phone_code, currency_code, currency_name, flag_emoji in countries:
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
                        "phone_code": phone_code,
                        "currency_code": currency_code,
                        "currency_name": currency_name,
                        "flag_emoji": flag_emoji,
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
