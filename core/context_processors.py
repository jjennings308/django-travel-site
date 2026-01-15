from django.conf import settings

def site_branding(request):
    return {
        "SITE_NAME": getattr(settings, "SITE_NAME", ""),
        "SITE_TAGLINE": getattr(settings, "SITE_TAGLINE", ""),
    }
