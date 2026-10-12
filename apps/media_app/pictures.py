# media_app/pictures.py
"""Picking the picture to show for an object that may borrow one from what it's linked to."""


def first_media(obj, *paths):
    """The first image found along ``paths`` (dotted FK paths ending in a Media FK,
    e.g. ``"venue.featured_media"``), or None; videos are skipped. Each step checks the ``*_id``
    first, so an empty link costs no query; select_related the paths to make it free."""
    for path in paths:
        current = obj
        for name in path.split("."):
            if current is None or getattr(current, f"{name}_id", None) is None:
                current = None
                break
            current = getattr(current, name)
        if current is not None and current.media_type == "image":
            return current
    return None
