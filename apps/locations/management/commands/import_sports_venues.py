from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from locations.models import Country, Region, City, POI
from approval_system.models import ApprovalStatus

User = get_user_model()


class Command(BaseCommand):
    """
    Import US National Parks as POIs.
    
    Now includes approval system integration - all imported national parks
    are automatically marked as APPROVED since these are system-level imports.
    """

    help = 'Import US National Parks as POIs with auto-approval'

    def add_arguments(self, parser):
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

        # Updated Professional Sports Venues data with durations in minutes
        venues_data = [
            {
                'name': 'Madison Square Garden',
                'state': 'New York',
                'city': 'New York',
                'lat': 40.7505,
                'lon': -73.9934,
                'description': 'Known as "The World\'s Most Famous Arena," it is the oldest major sporting facility in the New York metropolitan area.',
                'entry_fee': 150.00,
                'typical_duration': 150, # NBA/NHL average
            },
            {
                'name': 'Fenway Park',
                'state': 'Massachusetts',
                'city': 'Boston',
                'lat': 42.3467,
                'lon': -71.0972,
                'description': 'The oldest active ballpark in MLB, famous for the "Green Monster" left-field wall and its unique dimensions.',
                'entry_fee': 60.00,
                'typical_duration': 160, # MLB average (with pitch clock)
            },
            {
                'name': 'Lambeau Field',
                'state': 'Wisconsin',
                'city': 'Green Bay',
                'lat': 44.5013,
                'lon': -88.0622,
                'description': 'The oldest continually operating NFL stadium, famous for the "Lambeau Leap" and its frozen tundra history.',
                'entry_fee': 120.00,
                'typical_duration': 192, # NFL average
            },
            {
                'name': 'Wrigley Field',
                'state': 'Illinois',
                'city': 'Chicago',
                'lat': 41.9484,
                'lon': -87.6553,
                'description': 'The "Friendly Confines" is known for its ivy-covered brick outfield walls and hand-turned scoreboard.',
                'entry_fee': 55.00,
                'typical_duration': 160,
            },
            {
                'name': 'SoFi Stadium',
                'state': 'California',
                'city': 'Inglewood',
                'lat': 33.9535,
                'lon': -118.3390,
                'description': 'A state-of-the-art indoor-outdoor stadium featuring a massive "Infinity Screen" and serving as the home for two NFL teams.',
                'entry_fee': 175.00,
                'typical_duration': 192,
            },
            {
                'name': 'Crypto.com Arena',
                'state': 'California',
                'city': 'Los Angeles',
                'lat': 34.0430,
                'lon': -118.2673,
                'description': 'A centerpiece of the L.A. Live district, hosting multiple professional franchises and the Grammy Awards.',
                'entry_fee': 110.00,
                'typical_duration': 150,
            },
            {
                'name': 'AT&T Stadium',
                'state': 'Texas',
                'city': 'Arlington',
                'lat': 32.7473,
                'lon': -97.0945,
                'description': 'Often called "Jerry World," it features one of the largest high-definition video screens in the world and a retractable roof.',
                'entry_fee': 130.00,
                'typical_duration': 192,
            },
            {
                'name': 'Dodger Stadium',
                'state': 'California',
                'city': 'Los Angeles',
                'lat': 34.0739,
                'lon': -118.2400,
                'description': 'The largest baseball-specific stadium by capacity, nestled in the hills of Chavez Ravine with views of downtown LA.',
                'entry_fee': 45.00,
                'typical_duration': 160,
            },
            {
                'name': 'TD Garden',
                'state': 'Massachusetts',
                'city': 'Boston',
                'lat': 42.3662,
                'lon': -71.0621,
                'description': 'Built directly above Boston\'s North Station, it is the home of the Celtics and Bruins.',
                'entry_fee': 125.00,
                'typical_duration': 150,
            },
            {
                'name': 'Arrowhead Stadium',
                'state': 'Missouri',
                'city': 'Kansas City',
                'lat': 39.0489,
                'lon': -94.4839,
                'description': 'Holds the Guinness World Record for the loudest outdoor stadium in the world.',
                'entry_fee': 105.00,
                'typical_duration': 192,
            },
            {
                'name': 'Bell Centre',
                'state': 'Quebec',
                'city': 'Montreal',
                'lat': 45.4961,
                'lon': -73.5693,
                'description': 'The highest-capacity hockey arena in the NHL and widely considered one of the loudest.',
                'entry_fee': 95.00,
                'typical_duration': 150,
            }
        ]

# Get or create USA
        try:
            usa = Country.objects.get(iso_code='US')
            self.stdout.write(f"Found country: {usa}")
        except Country.DoesNotExist:
            self.stdout.write(self.style.ERROR('USA country not found. Please create it first.'))
            return

        # State abbreviations mapping
        state_codes = {
            'Alabama': 'AL',
            'Alaska': 'AK',
            'Arizona': 'AZ',
            'Arkansas': 'AR',
            'California': 'CA',
            'Colorado': 'CO',
            'Connecticut': 'CT',
            'Delaware': 'DE',
            'Florida': 'FL',
            'Georgia': 'GA',
            'Hawaii': 'HI',
            'Idaho': 'ID',
            'Illinois': 'IL',
            'Indiana': 'IN',
            'Iowa': 'IA',
            'Kansas': 'KS',
            'Kentucky': 'KY',
            'Louisiana': 'LA',
            'Maine': 'ME',
            'Maryland': 'MD',
            'Massachusetts': 'MA',
            'Michigan': 'MI',
            'Minnesota': 'MN',
            'Mississippi': 'MS',
            'Missouri': 'MO',
            'Montana': 'MT',
            'Nebraska': 'NE',
            'Nevada': 'NV',
            'New Hampshire': 'NH',
            'New Jersey': 'NJ',
            'New Mexico': 'NM',
            'New York': 'NY',
            'North Carolina': 'NC',
            'North Dakota': 'ND',
            'Ohio': 'OH',
            'Oklahoma': 'OK',
            'Oregon': 'OR',
            'Pennsylvania': 'PA',
            'Rhode Island': 'RI',
            'South Carolina': 'SC',
            'South Dakota': 'SD',
            'Tennessee': 'TN',
            'Texas': 'TX',
            'Utah': 'UT',
            'Vermont': 'VT',
            'Virginia': 'VA',
            'Washington': 'WA',
            'West Virginia': 'WV',
            'Wisconsin': 'WI',
            'Wyoming': 'WY',
            # Including territories with National Parks
            'American Samoa': 'AS',
            'US Virgin Islands': 'VI',
            'District of Columbia': 'DC'
        }
      
        created_count = 0
        updated_count = 0
        approved_count = 0
        skipped_count = 0

        for venue_data in venues_data:
            try:
                # Get or create region (state)
                state_code = state_codes.get(venue_data['state'], venue_data['state'][:2].upper())
                region, _ = Region.objects.get_or_create(
                    country=usa,
                    name=venue_data['state'],
                    defaults={
                        'code': state_code,
                        # Approval fields for auto-created regions
                        'approval_status': ApprovalStatus.APPROVED,
                        'submitted_by': approver,
                        'submitted_at': timezone.now(),
                        'reviewed_by': approver,
                        'reviewed_at': timezone.now(),
                    }
                )

                # Get or create city
                city, city_created = City.objects.get_or_create(
                    country=usa,
                    name=venue_data['city'],
                    defaults={
                        'region': region,
                        'latitude': Decimal(str(venue_data['lat'])),
                        'longitude': Decimal(str(venue_data['lon'])),
                        # Approval fields for auto-created cities
                        'approval_status': ApprovalStatus.APPROVED,
                        'submitted_by': approver,
                        'submitted_at': timezone.now(),
                        'reviewed_by': approver,
                        'reviewed_at': timezone.now(),
                    }
                )
                
                # Ensure existing cities are also approved
                if not city_created and city.approval_status != ApprovalStatus.APPROVED:
                    city.approval_status = ApprovalStatus.APPROVED
                    city.submitted_by = approver
                    city.submitted_at = timezone.now()
                    city.reviewed_by = approver
                    city.reviewed_at = timezone.now()
                    city.save()

                # Create or update POI
                poi, created = POI.objects.update_or_create(
                    city=city,
                    name=venue_data['name'],
                    defaults={
                        'poi_type': 'sports',
                        'latitude': Decimal(str(venue_data['lat'])),
                        'longitude': Decimal(str(venue_data['lon'])),
                        'description': venue_data['description'],
                        'entry_fee': Decimal(str(venue_data['entry_fee'])),
                        'entry_fee_currency': 'USD',
                        'typical_duration': venue_data['typical_duration'],
                        'is_featured': True,
                        'wheelchair_accessible': True,
                        'parking_available': True,
                        # Approval fields - mark as approved for system imports
                        'approval_status': ApprovalStatus.APPROVED,
                        'submitted_by': approver,
                        'submitted_at': timezone.now(),
                        'reviewed_by': approver,
                        'reviewed_at': timezone.now(),
                    }
                )

                if created:
                    created_count += 1
                    approved_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Created & Approved: {venue_data["name"]}')
                    )
                else:
                    updated_count += 1
                    # Ensure existing POI is approved
                    if poi.approval_status != ApprovalStatus.APPROVED:
                        poi.approval_status = ApprovalStatus.APPROVED
                        poi.reviewed_by = approver
                        poi.reviewed_at = timezone.now()
                        poi.save()
                        approved_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'↻ Updated: {venue_data["name"]}')
                    )

            except Exception as e:
                skipped_count += 1
                self.stdout.write(
                    self.style.ERROR(f'✗ Error importing {venue_data["name"]}: {str(e)}')
                )

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS(f'Import complete!'))
        self.stdout.write(self.style.SUCCESS(f'Created: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Updated: {updated_count}'))
        self.stdout.write(self.style.SUCCESS(f'Auto-Approved: {approved_count}'))
        if skipped_count > 0:
            self.stdout.write(self.style.ERROR(f'Errors: {skipped_count}'))
        self.stdout.write(self.style.SUCCESS(f'All imports marked as approved by: {approver.username}'))
        self.stdout.write(self.style.SUCCESS('='*60))