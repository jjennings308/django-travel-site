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
                'typical_duration': 480,
                'elevation_m': 2350,
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
                'elevation_m': 2070,
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
                'elevation_m': 1200,
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
                'elevation_m': 1200,
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
                'elevation_m': 2380,
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
                'elevation_m': 150,
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
                'elevation_m': 2070,
            },
            {
                'name': 'Great Smoky Mountains National Park',
                'state': 'Tennessee',
                'city': 'Gatlinburg',
                'lat': 35.6532,
                'lon': -83.5070,
                'description': "America's most visited national park, known for ancient mountains, diverse wildlife, and Appalachian culture.",
                'entry_fee': 0.00,
                'typical_duration': 360,
                'elevation_m': 460,
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
                'elevation_m': 960,
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
                'elevation_m': 180,
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
                'elevation_m': 2400,
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
                'elevation_m': 1520,
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
                'elevation_m': 820,
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
                'elevation_m': 520,
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
                'elevation_m': -86,
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
                'elevation_m': 2,
            },
            {
                'name': 'Denali National Park',
                'state': 'Alaska',
                'city': 'Denali Park',
                'lat': 63.1148,
                'lon': -151.1926,
                'description': "Home to North America's tallest peak, Denali (Mount McKinley), and vast subarctic wilderness.",
                'entry_fee': 15.00,
                'typical_duration': 480,
                'elevation_m': 640,
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
                'elevation_m': 1050,
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
                'elevation_m': 1350,
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
                'elevation_m': 510,
            },
            {
                'name': 'Badlands National Park',
                'state': 'South Dakota',
                'city': 'Interior',
                'lat': 43.8554,
                'lon': -102.3397,
                'description': 'Striking geologic deposits containing one of the world’s richest fossil beds.',
                'entry_fee': 30.00,
                'typical_duration': 240,
                'elevation_m': 750,
            },
            {
                'name': 'Big Bend National Park',
                'state': 'Texas',
                'city': 'Alpine',
                'lat': 29.1275,
                'lon': -103.2425,
                'description': 'Massive park protecting the Chisos Mountains and a large swath of the Chihuahuan Desert.',
                'entry_fee': 30.00,
                'typical_duration': 480,
                'elevation_m': 720,
            },
            {
                'name': 'Biscayne National Park',
                'state': 'Florida',
                'city': 'Homestead',
                'lat': 25.4824,
                'lon': -80.1604,
                'description': 'Protects aquamarine waters, emerald islands, and fish-filled coral reefs.',
                'entry_fee': 0.00,
                'typical_duration': 300,
                'elevation_m': 1,
            },
            {
                'name': 'Black Canyon of the Gunnison National Park',
                'state': 'Colorado',
                'city': 'Montrose',
                'lat': 38.5754,
                'lon': -107.7416,
                'description': 'Features some of the steepest cliffs and oldest rock in North America.',
                'entry_fee': 30.00,
                'typical_duration': 180,
                'elevation_m': 1980,
            },
            {
                'name': 'Capitol Reef National Park',
                'state': 'Utah',
                'city': 'Torrey',
                'lat': 38.3670,
                'lon': -111.2615,
                'description': 'Home to the Waterpocket Fold, a geologic monocline extending almost 100 miles.',
                'entry_fee': 20.00,
                'typical_duration': 240,
                'elevation_m': 1650,
            },
            {
                'name': 'Carlsbad Caverns National Park',
                'state': 'New Mexico',
                'city': 'Carlsbad',
                'lat': 32.1479,
                'lon': -104.5567,
                'description': 'High ancient sea ledges, deep rocky canyons, flowering cactus, and desert wildlife.',
                'entry_fee': 15.00,
                'typical_duration': 240,
                'elevation_m': 1340,
            },
            {
                'name': 'Channel Islands National Park',
                'state': 'California',
                'city': 'Ventura',
                'lat': 34.0069,
                'lon': -119.7785,
                'description': 'Five remarkable islands and their ocean environment, preserving unique animals and plants.',
                'entry_fee': 0.00,
                'typical_duration': 480,
                'elevation_m': 5,
            },
            {
                'name': 'Congaree National Park',
                'state': 'South Carolina',
                'city': 'Hopkins',
                'lat': 33.7948,
                'lon': -80.7821,
                'description': 'The largest intact expanse of old growth bottomland hardwood forest in the Southeast.',
                'entry_fee': 0.00,
                'typical_duration': 180,
                'elevation_m': 30,
            },
            {
                'name': 'Crater Lake National Park',
                'state': 'Oregon',
                'city': 'Crater Lake',
                'lat': 42.8684,
                'lon': -122.1685,
                'description': 'The deepest lake in the USA, formed by the collapse of an ancient volcano.',
                'entry_fee': 30.00,
                'typical_duration': 240,
                'elevation_m': 1880,
            },
            {
                'name': 'Cuyahoga Valley National Park',
                'state': 'Ohio',
                'city': 'Brecksville',
                'lat': 41.2808,
                'lon': -81.5678,
                'description': 'A refuge for native plants and wildlife along the Cuyahoga River between Cleveland and Akron.',
                'entry_fee': 0.00,
                'typical_duration': 180,
                'elevation_m': 210,
            },
            {
                'name': 'Dry Tortugas National Park',
                'state': 'Florida',
                'city': 'Key West',
                'lat': 24.6285,
                'lon': -82.8732,
                'description': 'A 19th-century fort and crystal clear waters 70 miles west of Key West.',
                'entry_fee': 15.00,
                'typical_duration': 360,
                'elevation_m': 2,
            },
            {
                'name': 'Gates of the Arctic National Park',
                'state': 'Alaska',
                'city': 'Bettles',
                'lat': 67.8860,
                'lon': -153.3000,
                'description': 'An untouched wilderness with no roads or trails, lying entirely north of the Arctic Circle.',
                'entry_fee': 0.00,
                'typical_duration': 1440,
                'elevation_m': 300,
            },
            {
                'name': 'Gateway Arch National Park',
                'state': 'Missouri',
                'city': 'St. Louis',
                'lat': 38.6247,
                'lon': -90.1848,
                'description': 'The gateway to the west, commemorating the Lewis and Clark expedition and westward expansion.',
                'entry_fee': 3.00,
                'typical_duration': 120,
                'elevation_m': 140,
            },
            {
                'name': 'Glacier Bay National Park',
                'state': 'Alaska',
                'city': 'Gustavus',
                'lat': 58.6658,
                'lon': -136.9002,
                'description': 'A highlight of Alaska’s Inside Passage and part of a 25-million-acre World Heritage site.',
                'entry_fee': 0.00,
                'typical_duration': 480,
                'elevation_m': 10,
            },
            {
                'name': 'Grand Basin National Park',
                'state': 'Nevada',
                'city': 'Baker',
                'lat': 38.9836,
                'lon': -114.3000,
                'description': 'Known for its ancient bristlecone pines and the Lehman Caves.',
                'entry_fee': 0.00,
                'typical_duration': 240,
                'elevation_m': 2050,
            },
            {
                'name': 'Great Sand Dunes National Park',
                'state': 'Colorado',
                'city': 'Mosca',
                'lat': 37.7916,
                'lon': -105.5943,
                'description': 'The tallest sand dunes in North America, set against the backdrop of the Sangre de Cristo Mountains.',
                'entry_fee': 25.00,
                'typical_duration': 240,
                'elevation_m': 2510,
            },
            {
                'name': 'Guadalupe Mountains National Park',
                'state': 'Texas',
                'city': 'Salt Flat',
                'lat': 31.9484,
                'lon': -104.8683,
                'description': 'Contains the world’s most extensive Permian fossil reef and the highest point in Texas.',
                'entry_fee': 10.00,
                'typical_duration': 300,
                'elevation_m': 1650,
            },
            {
                'name': 'Haleakalā National Park',
                'state': 'Hawaii',
                'city': 'Kula',
                'lat': 20.7012,
                'lon': -156.1733,
                'description': 'Preserves the volcanic landscape of Maui and the unique flora and fauna that live there.',
                'entry_fee': 30.00,
                'typical_duration': 300,
                'elevation_m': 2100,
            },
            {
                'name': 'Hawaiʻi Volcanoes National Park',
                'state': 'Hawaii',
                'city': 'Hawaii National Park',
                'lat': 19.4194,
                'lon': -155.2885,
                'description': 'Protects some of the most unique geological, biological, and cultural landscapes in the world.',
                'entry_fee': 30.00,
                'typical_duration': 360,
                'elevation_m': 1200,
            },
            {
                'name': 'Hot Springs National Park',
                'state': 'Arkansas',
                'city': 'Hot Springs',
                'lat': 34.5217,
                'lon': -93.0423,
                'description': 'An urban park featuring historic bathhouses and thermal springs.',
                'entry_fee': 0.00,
                'typical_duration': 180,
                'elevation_m': 180,
            },
            {
                'name': 'Indiana Dunes National Park',
                'state': 'Indiana',
                'city': 'Porter',
                'lat': 41.6533,
                'lon': -87.0524,
                'description': 'Miles of beaches, sand dunes, woodlands, and marshes along Lake Michigan.',
                'entry_fee': 25.00,
                'typical_duration': 240,
                'elevation_m': 190,
            },
            {
                'name': 'Isle Royale National Park',
                'state': 'Michigan',
                'city': 'Houghton',
                'lat': 47.9959,
                'lon': -88.9040,
                'description': 'A rugged, isolated island in Lake Superior, accessible only by boat or seaplane.',
                'entry_fee': 7.00,
                'typical_duration': 1440,
                'elevation_m': 240,
            },
            {
                'name': 'Katmai National Park',
                'state': 'Alaska',
                'city': 'King Salmon',
                'lat': 58.5079,
                'lon': -154.9059,
                'description': 'Famous for its brown bears and the Valley of Ten Thousand Smokes.',
                'entry_fee': 0.00,
                'typical_duration': 480,
                'elevation_m': 20,
            },
            {
                'name': 'Kenai Fjords National Park',
                'state': 'Alaska',
                'city': 'Seward',
                'lat': 59.9171,
                'lon': -149.8611,
                'description': 'Where the ice age still lingers, featuring glaciers and abundant marine wildlife.',
                'entry_fee': 0.00,
                'typical_duration': 360,
                'elevation_m': 30,
            },
            {
                'name': 'Kings Canyon National Park',
                'state': 'California',
                'city': 'Grant Grove Village',
                'lat': 36.8879,
                'lon': -118.5551,
                'description': 'Features giant sequoias and one of the deepest canyons in the United States.',
                'entry_fee': 35.00,
                'typical_duration': 360,
                'elevation_m': 1950,
            },
            {
                'name': 'Kobuk Valley National Park',
                'state': 'Alaska',
                'city': 'Kotzebue',
                'lat': 67.3331,
                'lon': -159.1230,
                'description': 'Home to vast sand dunes and the annual migration of half a million caribou.',
                'entry_fee': 0.00,
                'typical_duration': 1440,
                'elevation_m': 30,
            },
            {
                'name': 'Lake Clark National Park',
                'state': 'Alaska',
                'city': 'Port Alsworth',
                'lat': 60.4113,
                'lon': -154.3235,
                'description': 'A land of stunning beauty where volcanoes steam and salmon swim.',
                'entry_fee': 0.00,
                'typical_duration': 480,
                'elevation_m': 320,
            },
            {
                'name': 'Lassen Volcanic National Park',
                'state': 'California',
                'city': 'Mineral',
                'lat': 40.4977,
                'lon': -121.4207,
                'description': 'Boasts hydrothermal sites like Bumpass Hell and the massive Lassen Peak volcano.',
                'entry_fee': 30.00,
                'typical_duration': 300,
                'elevation_m': 1750,
            },
            {
                'name': 'Mammoth Cave National Park',
                'state': 'Kentucky',
                'city': 'Mammoth Cave',
                'lat': 37.1870,
                'lon': -86.1005,
                'description': 'The world’s longest known cave system.',
                'entry_fee': 0.00,
                'typical_duration': 240,
                'elevation_m': 210,
            },
            {
                'name': 'Mesa Verde National Park',
                'state': 'Colorado',
                'city': 'Cortez',
                'lat': 37.2309,
                'lon': -108.4618,
                'description': 'Preserves the cultural heritage of the Ancestral Pueblo people.',
                'entry_fee': 30.00,
                'typical_duration': 300,
                'elevation_m': 2070,
            },
            {
                'name': 'National Park of American Samoa',
                'state': 'American Samoa',
                'city': 'Pago Pago',
                'lat': -14.2583,
                'lon': -170.6833,
                'description': 'One of the most remote parks, preserving coral reefs and tropical rainforests.',
                'entry_fee': 0.00,
                'typical_duration': 300,
                'elevation_m': 20,
            },
            {
                'name': 'New River Gorge National Park',
                'state': 'West Virginia',
                'city': 'Glen Jean',
                'lat': 37.8782,
                'lon': -81.0160,
                'description': 'One of the oldest rivers on the continent, famous for its massive bridge and whitewater rafting.',
                'entry_fee': 0.00,
                'typical_duration': 300,
                'elevation_m': 580,
            },
            {
                'name': 'North Cascades National Park',
                'state': 'Washington',
                'city': 'Sedro-Woolley',
                'lat': 48.7718,
                'lon': -121.2985,
                'description': 'An alpine landscape with over 300 glaciers and jagged peaks.',
                'entry_fee': 0.00,
                'typical_duration': 420,
                'elevation_m': 170,
            },
            {
                'name': 'Petrified Forest National Park',
                'state': 'Arizona',
                'city': 'Holbrook',
                'lat': 34.9100,
                'lon': -109.8068,
                'description': 'Known for its large deposits of petrified wood and the colorful Painted Desert.',
                'entry_fee': 25.00,
                'typical_duration': 180,
                'elevation_m': 1660,
            },
            {
                'name': 'Pinnacles National Park',
                'state': 'California',
                'city': 'Paicines',
                'lat': 36.4906,
                'lon': -121.1819,
                'description': 'Rock spires and talus caves formed by an ancient volcano.',
                'entry_fee': 30.00,
                'typical_duration': 240,
                'elevation_m': 390,
            },
            {
                'name': 'Redwood National Park',
                'state': 'California',
                'city': 'Crescent City',
                'lat': 41.2132,
                'lon': -124.0046,
                'description': 'Home to the tallest trees on Earth and a stunning Pacific coastline.',
                'entry_fee': 0.00,
                'typical_duration': 360,
                'elevation_m': 60,
            },
            {
                'name': 'Saguaro National Park',
                'state': 'Arizona',
                'city': 'Tucson',
                'lat': 32.2967,
                'lon': -111.1666,
                'description': 'Protects the giant saguaro cactus, the symbol of the American West.',
                'entry_fee': 25.00,
                'typical_duration': 180,
                'elevation_m': 820,
            },
            {
                'name': 'Theodore Roosevelt National Park',
                'state': 'North Dakota',
                'city': 'Medora',
                'lat': 46.9790,
                'lon': -103.5387,
                'description': 'Badlands where President Theodore Roosevelt once hunted bison.',
                'entry_fee': 30.00,
                'typical_duration': 240,
                'elevation_m': 700,
            },
            {
                'name': 'Virgin Islands National Park',
                'state': 'US Virgin Islands',
                'city': 'St. John',
                'lat': 18.3333,
                'lon': -64.7333,
                'description': 'Covers most of the island of St. John, known for white sand beaches and coral reefs.',
                'entry_fee': 0.00,
                'typical_duration': 360,
                'elevation_m': 10,
            },
            {
                'name': 'Voyageurs National Park',
                'state': 'Minnesota',
                'city': 'International Falls',
                'lat': 48.4771,
                'lon': -92.8378,
                'description': 'A water-based park near the Canadian border, accessible primarily by boat.',
                'entry_fee': 0.00,
                'typical_duration': 360,
                'elevation_m': 340,
            },
            {
                'name': 'White Sands National Park',
                'state': 'New Mexico',
                'city': 'Alamogordo',
                'lat': 32.7872,
                'lon': -106.3257,
                'description': 'The world’s largest gypsum dunefield, creating a landscape of glistening white sand.',
                'entry_fee': 25.00,
                'typical_duration': 180,
                'elevation_m': 1230,
            },
            {
                'name': 'Wind Cave National Park',
                'state': 'South Dakota',
                'city': 'Hot Springs',
                'lat': 43.5700,
                'lon': -103.4799,
                'description': 'One of the world’s longest and most complex caves, featuring rare boxwork formations.',
                'entry_fee': 0.00,
                'typical_duration': 180,
                'elevation_m': 1280,
            },
            {
                'name': 'Wrangell–St. Elias National Park',
                'state': 'Alaska',
                'city': 'Copper Center',
                'lat': 61.7104,
                'lon': -142.9850,
                'description': 'The largest national park in the USA, containing 9 of the 16 highest peaks in the country.',
                'entry_fee': 0.00,
                'typical_duration': 480,
                'elevation_m': 300,
            },
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

        for park_data in parks_data:
            try:
                # Get or create region (state)
                state_code = state_codes.get(park_data['state'], park_data['state'][:2].upper())
                region, _ = Region.objects.get_or_create(
                    country=usa,
                    name=park_data['state'],
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
                    name=park_data['city'],
                    defaults={
                        'region': region,
                        'latitude': Decimal(str(park_data['lat'])),
                        'longitude': Decimal(str(park_data['lon'])),
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
                        self.style.SUCCESS(f'✓ Created & Approved: {park_data["name"]}')
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
                        self.style.WARNING(f'↻ Updated: {park_data["name"]}')
                    )

            except Exception as e:
                skipped_count += 1
                self.stdout.write(
                    self.style.ERROR(f'✗ Error importing {park_data["name"]}: {str(e)}')
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