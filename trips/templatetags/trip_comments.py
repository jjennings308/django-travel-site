"""Template filters for rendering comment threads.

Comments are grouped by target in the view, as ``{(kind, pk): [comments]}`` for
direct lookup and ``{kind: {pk: [...]}}`` for the template. The nested form needs
a way to index it by a *variable* key, which the Django template language cannot
do — ``{{ mapping[key] }}`` parses, but ``key`` is looked up as a context
variable, so it never resolves to an integer pk.

Usage in a template::

    {% load trip_comments %}
    {% with by_pk=comments_by_target.day %}
      {% with thread=by_pk|dictkey:day.pk %}
        ...
      {% endwith %}
    {% endwith %}
"""

from django import template

register = template.Library()


@register.filter
def dictkey(mapping, key):
    """``mapping[key]``, or an empty list if absent.

    Returns an empty list rather than ``None`` so a template can use
    ``{% if thread %}`` and ``{% for comment in thread %}`` on the result without
    a guard for each. That matters here because a thread is absent for the vast
    majority of days and sections on a trip.
    """
    if not mapping:
        return []
    try:
        return mapping[key]
    except (KeyError, IndexError, TypeError):
        return []
