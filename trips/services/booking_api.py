# trips/services/booking_api.py
"""
API service stubs for external booking integrations.
These are placeholder implementations that will be replaced with actual API calls.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import random
from typing import Dict, List, Optional


class FlightBookingAPI:
    """
    Stub for flight booking API integration.
    In production, this would connect to services like:
    - Amadeus API
    - Skyscanner API
    - Kiwi.com API
    - Google Flights API
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or "PLACEHOLDER_API_KEY"
        self.base_url = "https://api.flight-booking-service.example.com"
    
    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: datetime,
        return_date: Optional[datetime] = None,
        passengers: int = 1,
        cabin_class: str = "economy"
    ) -> List[Dict]:
        """
        Search for available flights.
        Returns mock data - replace with actual API call.
        """
        # Mock flight data
        airlines = ["United", "Delta", "American", "JetBlue", "Southwest"]
        
        flights = []
        for i in range(5):
            base_price = random.randint(200, 800)
            
            flight = {
                "flight_id": f"FL{random.randint(1000, 9999)}",
                "airline": random.choice(airlines),
                "flight_number": f"{random.choice(['UA', 'DL', 'AA', 'B6', 'WN'])}{random.randint(100, 999)}",
                "origin": origin,
                "destination": destination,
                "departure_time": (departure_date + timedelta(hours=random.randint(6, 20))).isoformat(),
                "arrival_time": (departure_date + timedelta(hours=random.randint(8, 24))).isoformat(),
                "duration_minutes": random.randint(120, 480),
                "stops": random.randint(0, 2),
                "cabin_class": cabin_class,
                "price": Decimal(str(base_price * passengers)),
                "currency": "USD",
                "seats_available": random.randint(1, 50),
                "baggage_included": random.choice([True, False]),
                "refundable": random.choice([True, False])
            }
            
            # Add return flight if round trip
            if return_date:
                flight["return_flight"] = {
                    "flight_number": f"{random.choice(['UA', 'DL', 'AA', 'B6', 'WN'])}{random.randint(100, 999)}",
                    "departure_time": (return_date + timedelta(hours=random.randint(6, 20))).isoformat(),
                    "arrival_time": (return_date + timedelta(hours=random.randint(8, 24))).isoformat(),
                }
                flight["price"] = flight["price"] * Decimal("1.8")  # Round trip pricing
            
            flights.append(flight)
        
        return sorted(flights, key=lambda x: x["price"])
    
    def book_flight(self, flight_id: str, passenger_details: Dict) -> Dict:
        """
        Book a specific flight.
        Returns mock confirmation - replace with actual API call.
        """
        confirmation = {
            "success": True,
            "booking_id": f"BK{random.randint(100000, 999999)}",
            "confirmation_number": f"CONF{random.randint(100000, 999999)}",
            "flight_id": flight_id,
            "status": "confirmed",
            "passenger_details": passenger_details,
            "booking_url": f"https://booking-service.example.com/view/{flight_id}",
            "payment_required": True,
            "total_amount": Decimal("549.99"),
            "currency": "USD"
        }
        
        return confirmation
    
    def cancel_booking(self, booking_id: str) -> Dict:
        """Cancel a flight booking"""
        return {
            "success": True,
            "booking_id": booking_id,
            "status": "cancelled",
            "refund_amount": Decimal("450.00"),
            "refund_currency": "USD",
            "refund_timeline_days": 7
        }


class HotelBookingAPI:
    """
    Stub for hotel booking API integration.
    In production, this would connect to services like:
    - Booking.com API
    - Expedia API
    - Hotels.com API
    - Airbnb API
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or "PLACEHOLDER_API_KEY"
        self.base_url = "https://api.hotel-booking-service.example.com"
    
    def search_hotels(
        self,
        destination: str,
        check_in: datetime,
        check_out: datetime,
        rooms: int = 1,
        guests: int = 2,
        max_price: Optional[Decimal] = None
    ) -> List[Dict]:
        """
        Search for available hotels.
        Returns mock data - replace with actual API call.
        """
        hotel_names = [
            "Grand Plaza Hotel", "Seaside Resort & Spa", "Downtown Boutique Inn",
            "Mountain View Lodge", "City Center Suites"
        ]
        
        hotels = []
        nights = (check_out - check_in).days
        
        for i in range(5):
            price_per_night = random.randint(80, 400)
            if max_price and Decimal(str(price_per_night)) > max_price:
                price_per_night = int(max_price) - 20
            
            hotel = {
                "hotel_id": f"HTL{random.randint(1000, 9999)}",
                "name": random.choice(hotel_names),
                "address": f"{random.randint(100, 999)} Main St, {destination}",
                "rating": round(random.uniform(3.5, 5.0), 1),
                "review_count": random.randint(50, 500),
                "price_per_night": Decimal(str(price_per_night)),
                "total_price": Decimal(str(price_per_night * nights * rooms)),
                "currency": "USD",
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "rooms_available": random.randint(1, 10),
                "amenities": random.sample([
                    "Free WiFi", "Pool", "Gym", "Restaurant", 
                    "Spa", "Free Parking", "Airport Shuttle", "Pet Friendly"
                ], k=random.randint(3, 6)),
                "room_type": random.choice(["Standard", "Deluxe", "Suite"]),
                "cancellation_policy": random.choice([
                    "Free cancellation up to 24 hours before check-in",
                    "Free cancellation up to 7 days before check-in",
                    "Non-refundable"
                ])
            }
            
            hotels.append(hotel)
        
        return sorted(hotels, key=lambda x: x["total_price"])
    
    def book_hotel(self, hotel_id: str, guest_details: Dict) -> Dict:
        """
        Book a specific hotel.
        Returns mock confirmation - replace with actual API call.
        """
        confirmation = {
            "success": True,
            "booking_id": f"HB{random.randint(100000, 999999)}",
            "confirmation_number": f"HCONF{random.randint(100000, 999999)}",
            "hotel_id": hotel_id,
            "status": "confirmed",
            "guest_details": guest_details,
            "booking_url": f"https://hotel-booking.example.com/view/{hotel_id}",
            "payment_required": True,
            "total_amount": Decimal("899.99"),
            "currency": "USD",
            "special_requests": guest_details.get("special_requests", "")
        }
        
        return confirmation
    
    def cancel_booking(self, booking_id: str) -> Dict:
        """Cancel a hotel booking"""
        return {
            "success": True,
            "booking_id": booking_id,
            "status": "cancelled",
            "refund_amount": Decimal("899.99"),
            "refund_currency": "USD",
            "cancellation_fee": Decimal("0.00")
        }


class ActivityBookingAPI:
    """
    Stub for activity/tour booking API integration.
    In production, this would connect to services like:
    - Viator API
    - GetYourGuide API
    - Klook API
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or "PLACEHOLDER_API_KEY"
        self.base_url = "https://api.activity-booking-service.example.com"
    
    def search_activities(
        self,
        destination: str,
        activity_date: Optional[datetime] = None,
        category: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for available activities and tours.
        Returns mock data - replace with actual API call.
        """
        activity_names = [
            "City Walking Tour", "Cooking Class Experience", "Museum Skip-the-Line",
            "Wine Tasting Tour", "Sunset Cruise", "Adventure Zip Line",
            "Cultural Heritage Tour", "Food Market Visit"
        ]
        
        categories = ["Tours", "Food & Drink", "Adventure", "Culture", "Water Activities"]
        
        activities = []
        for i in range(6):
            duration_hours = random.choice([2, 3, 4, 6, 8])
            
            activity = {
                "activity_id": f"ACT{random.randint(1000, 9999)}",
                "name": random.choice(activity_names),
                "category": category or random.choice(categories),
                "description": "Amazing experience exploring the best of the destination",
                "destination": destination,
                "duration_hours": duration_hours,
                "price_per_person": Decimal(str(random.randint(30, 200))),
                "currency": "USD",
                "rating": round(random.uniform(4.0, 5.0), 1),
                "review_count": random.randint(10, 300),
                "max_participants": random.randint(10, 50),
                "includes": random.sample([
                    "Guide", "Entrance Fees", "Transportation", 
                    "Meals", "Equipment", "Photos"
                ], k=random.randint(2, 4)),
                "meeting_point": f"Central Square, {destination}",
                "languages": ["English", random.choice(["Spanish", "French", "German"])],
                "cancellation_policy": "Free cancellation up to 24 hours before"
            }
            
            activities.append(activity)
        
        return sorted(activities, key=lambda x: x["rating"], reverse=True)
    
    def book_activity(self, activity_id: str, participant_details: Dict) -> Dict:
        """
        Book a specific activity.
        Returns mock confirmation - replace with actual API call.
        """
        confirmation = {
            "success": True,
            "booking_id": f"AB{random.randint(100000, 999999)}",
            "confirmation_number": f"ACONF{random.randint(100000, 999999)}",
            "activity_id": activity_id,
            "status": "confirmed",
            "participant_details": participant_details,
            "voucher_url": f"https://activity-booking.example.com/voucher/{activity_id}",
            "payment_required": True,
            "total_amount": Decimal("149.99"),
            "currency": "USD",
            "meeting_instructions": "Meet at the fountain in Central Square 15 minutes before start time"
        }
        
        return confirmation
    
    def cancel_booking(self, booking_id: str) -> Dict:
        """Cancel an activity booking"""
        return {
            "success": True,
            "booking_id": booking_id,
            "status": "cancelled",
            "refund_amount": Decimal("149.99"),
            "refund_currency": "USD"
        }


class PaymentProcessor:
    """
    Stub for payment processing.
    In production, this would integrate with:
    - Stripe
    - PayPal
    - Square
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or "PLACEHOLDER_API_KEY"
    
    def process_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_method: Dict,
        description: str
    ) -> Dict:
        """
        Process a payment.
        Returns mock result - replace with actual payment gateway.
        """
        # Simulate payment processing
        success = random.choice([True, True, True, False])  # 75% success rate
        
        if success:
            return {
                "success": True,
                "transaction_id": f"TXN{random.randint(1000000, 9999999)}",
                "amount": amount,
                "currency": currency,
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "receipt_url": f"https://payments.example.com/receipt/TXN{random.randint(1000000, 9999999)}"
            }
        else:
            return {
                "success": False,
                "error_code": "PAYMENT_DECLINED",
                "error_message": "Payment was declined by the issuing bank",
                "amount": amount,
                "currency": currency
            }
    
    def refund_payment(self, transaction_id: str, amount: Optional[Decimal] = None) -> Dict:
        """Process a refund"""
        return {
            "success": True,
            "refund_id": f"REF{random.randint(1000000, 9999999)}",
            "transaction_id": transaction_id,
            "amount": amount or Decimal("100.00"),
            "status": "refunded",
            "timestamp": datetime.now().isoformat()
        }


# Convenience functions for easy import
def get_flight_api() -> FlightBookingAPI:
    """Get flight booking API instance"""
    return FlightBookingAPI()


def get_hotel_api() -> HotelBookingAPI:
    """Get hotel booking API instance"""
    return HotelBookingAPI()


def get_activity_api() -> ActivityBookingAPI:
    """Get activity booking API instance"""
    return ActivityBookingAPI()


def get_payment_processor() -> PaymentProcessor:
    """Get payment processor instance"""
    return PaymentProcessor()
