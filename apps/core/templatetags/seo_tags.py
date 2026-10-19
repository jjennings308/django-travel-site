"""``{{ data|jsonld }}``: a dict as a ``<script type="application/ld+json">`` block (site roadmap R22),
escaped like ``json_script`` so a name containing ``</script>`` can't break out."""
import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


@register.filter
def jsonld(data):
    if not data:
        return ""
    text = json.dumps(data, ensure_ascii=False, default=str).translate(_ESCAPES)
    return mark_safe(f'<script type="application/ld+json">{text}</script>')
