from django.utils import timezone

def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = timezone.now().date()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
