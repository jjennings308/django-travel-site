# locations/management/commands/import_national_parks.py
from django.core.management.base import BaseCommand
from locations.models import Country, Region, City, POI
from decimal import Decimal


class Command(BaseCommand):
    help = 'Import US National Parks as POIs'

    def handle(self, *args, **options):
        # National Parks data
        parks_data = [
            {
                'name': 'Yellowstone National Park',
                'state': 'Wyoming',
                'city': 'Yellowstone',
                'lat': 44.4280,
                'lon': -110.5885,
                'description': 'The first national park in the world, featuring geothermal wonders including Old Faithful geyser, diverse wildlife, and stunning mountain scenery.',
                'entry_fee': 35.00,
                'typical_duration': 480,  # 8 hours
            },
            {
                'name': 'Grand Canyon National Park',
                'state': 'Arizona',
                'city': 'Grand Canyon',
                'lat': 36.1069,
                'lon': -112.1129,
                'description': 'One of the Seven Natural Wonders of the World, showcasing immense canyon carved by the Colorado River with breathtaking vistas.',
                'entry_fee': 35.00,
                'typical_duration': 360,
            },
            {
                'name': 'Yosemite National Park',
                'state': 'California',
                'city': 'Yosemite Valley',
                'lat': 37.8651,
                'lon': -119.5383,
                'description': 'Famous for granite cliffs, waterfalls, giant sequoia groves, and biological diversity, including El Capitan and Half Dome.',
                'entry_fee': 35.00,
                'typical_duration': 420,
            },
            {
                'name': 'Zion National Park',
                'state': 'Utah',
                'city': 'Springdale',
                'lat': 37.2982,
                'lon': -113.0263,
                'description': 'Known for its towering sandstone cliffs, narrow slot canyons, and scenic Virgin River corridor.',
                'entry_fee': 35.00,
                'typical_duration': 300,
            },
            {
                'name': 'Rocky Mountain National Park',
                'state': 'Colorado',
                'city': 'Estes Park',
                'lat': 40.3428,
                'lon': -105.6836,
                'description': 'Features majestic mountain peaks, alpine lakes, and diverse ecosystems from montane to alpine tundra.',
                'entry_fee': 30.00,
                'typical_duration': 360,
            },
            {
                'name': 'Acadia National Park',
                'state': 'Maine',
                'city': 'Bar Harbor',
                'lat': 44.3386,
                'lon': -68.2733,
                'description': 'Coastal park featuring rocky beaches, woodland, and granite peaks including Cadillac Mountain.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
            {
                'name': 'Grand Teton National Park',
                'state': 'Wyoming',
                'city': 'Jackson',
                'lat': 43.7904,
                'lon': -110.6818,
                'description': 'Spectacular mountain scenery with the Teton Range rising dramatically above Jackson Hole valley.',
                'entry_fee': 35.00,
                'typical_duration': 360,
            },
            {
                'name': 'Great Smoky Mountains National Park',
                'state': 'Tennessee',
                'city': 'Gatlinburg',
                'lat': 35.6532,
                'lon': -83.5070,
                'description': "America's most visited national park, known for ancient mountains, diverse wildlife, and Appalachian culture.",
                'entry_fee': 0.00,  # Free entry
                'typical_duration': 360,
            },
            {
                'name': 'Glacier National Park',
                'state': 'Montana',
                'city': 'West Glacier',
                'lat': 48.7596,
                'lon': -113.7870,
                'description': 'Pristine wilderness with glacier-carved peaks, alpine meadows, and the scenic Going-to-the-Sun Road.',
                'entry_fee': 35.00,
                'typical_duration': 420,
            },
            {
                'name': 'Olympic National Park',
                'state': 'Washington',
                'city': 'Port Angeles',
                'lat': 47.8021,
                'lon': -123.6044,
                'description': 'Diverse ecosystems including temperate rainforest, alpine areas, and rugged Pacific coastline.',
                'entry_fee': 30.00,
                'typical_duration': 360,
            },
            {
                'name': 'Bryce Canyon National Park',
                'state': 'Utah',
                'city': 'Bryce Canyon City',
                'lat': 37.5930,
                'lon': -112.1871,
                'description': 'Unique geology featuring hoodoos - spire-shaped rock formations in vibrant red, orange, and white colors.',
                'entry_fee': 35.00,
                'typical_duration': 240,
            },
            {
                'name': 'Arches National Park',
                'state': 'Utah',
                'city': 'Moab',
                'lat': 38.7331,
                'lon': -109.5925,
                'description': 'Home to over 2,000 natural stone arches, including the iconic Delicate Arch.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
            {
                'name': 'Joshua Tree National Park',
                'state': 'California',
                'city': 'Twentynine Palms',
                'lat': 33.8734,
                'lon': -115.9010,
                'description': 'Where the Mojave and Colorado deserts meet, featuring unique Joshua trees and excellent rock climbing.',
                'entry_fee': 30.00,
                'typical_duration': 240,
            },
            {
                'name': 'Sequoia National Park',
                'state': 'California',
                'city': 'Three Rivers',
                'lat': 36.4864,
                'lon': -118.5658,
                'description': 'Home to giant sequoia trees, including General Sherman, the largest tree on Earth by volume.',
                'entry_fee': 35.00,
                'typical_duration': 360,
            },
            {
                'name': 'Death Valley National Park',
                'state': 'California',
                'city': 'Death Valley',
                'lat': 36.5323,
                'lon': -116.9325,
                'description': 'Hottest, driest, and lowest national park, featuring dramatic desert landscapes and unique geology.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
            {
                'name': 'Everglades National Park',
                'state': 'Florida',
                'city': 'Homestead',
                'lat': 25.2866,
                'lon': -80.8987,
                'description': 'Largest tropical wilderness in the US, featuring wetlands, mangroves, and diverse wildlife including alligators.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
            {
                'name': 'Denali National Park',
                'state': 'Alaska',
                'city': 'Denali Park',
                'lat': 63.1148,
                'lon': -151.1926,
                'description': 'Home to North America\'s tallest peak, Denali (Mount McKinley), and vast subarctic wilderness.',
                'entry_fee': 15.00,
                'typical_duration': 480,
            },
            {
                'name': 'Shenandoah National Park',
                'state': 'Virginia',
                'city': 'Luray',
                'lat': 38.2928,
                'lon': -78.6795,
                'description': 'Blue Ridge Mountains park offering scenic Skyline Drive, waterfalls, and Appalachian Trail hiking.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
            {
                'name': 'Canyonlands National Park',
                'state': 'Utah',
                'city': 'Moab',
                'lat': 38.2135,
                'lon': -109.8801,
                'description': 'Dramatic desert landscape carved by the Colorado and Green Rivers into countless canyons and mesas.',
                'entry_fee': 30.00,
                'typical_duration': 360,
            },
            {
                'name': 'Mount Rainier National Park',
                'state': 'Washington',
                'city': 'Ashford',
                'lat': 46.8800,
                'lon': -121.7269,
                'description': 'Features an iconic active volcano covered in glaciers, surrounded by wildflower meadows and old-growth forests.',
                'entry_fee': 30.00,
                'typical_duration': 300,
            },
        ]

        # Get or create USA
        try:
            usa = Country.objects.get(iso_code='US')
            self.stdout.write(f"Found country: {usa}")
        except Country.DoesNotExist:
            self.stdout.write(self.style.ERROR('USA country not found. Please create it first.'))
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for park_data in parks_data:
            try:
                # Get or create region (state)
                region, _ = Region.objects.get_or_create(
                    country=usa,
                    name=park_data['state'],
                    defaults={'code': park_data['state'][:2].upper()}
                )

                # Get or create city
                city, city_created = City.objects.get_or_create(
                    country=usa,
                    name=park_data['city'],
                    defaults={
                        'region': region,
                        'latitude': Decimal(str(park_data['lat'])),
                        'longitude': Decimal(str(park_data['lon'])),
                    }
                )

                # Create or update POI
                poi, created = POI.objects.update_or_create(
                    city=city,
                    name=park_data['name'],
                    defaults={
                        'poi_type': 'nature',
                        'latitude': Decimal(str(park_data['lat'])),
                        'longitude': Decimal(str(park_data['lon'])),
                        'description': park_data['description'],
                        'entry_fee': Decimal(str(park_data['entry_fee'])),
                        'entry_fee_currency': 'USD',
                        'typical_duration': park_data['typical_duration'],
                        'is_featured': True,
                        'wheelchair_accessible': True,
                        'parking_available': True,
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Created: {park_data["name"]}')
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'↻ Updated: {park_data["name"]}')
                    )

            except Exception as e:
                skipped_count += 1
                self.stdout.write(
                    self.style.ERROR(f'✗ Error importing {park_data["name"]}: {str(e)}')
                )

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*50))
        self.stdout.write(self.style.SUCCESS(f'Import complete!'))
        self.stdout.write(self.style.SUCCESS(f'Created: {created_count}'))
        self.stdout.write(self.style.WARNING(f'Updated: {updated_count}'))
        if skipped_count > 0:
            self.stdout.write(self.style.ERROR(f'Errors: {skipped_count}'))
        self.stdout.write(self.style.SUCCESS('='*50))