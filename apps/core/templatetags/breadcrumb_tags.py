"""``{% breadcrumbs %}…{% endbreadcrumbs %}`` (ux-consistency V2): the site's one breadcrumb trail
(``partials/_breadcrumbs.html``, chevrons) from links written in the template, for pages whose views don't pass a
``breadcrumb_list``:

    {% load breadcrumb_tags %}
    {% breadcrumbs %}
      <a href="{% url 'trips:trip_list' %}">Trips</a>
      <a href="{% url 'trips:trip_detail' trip.pk %}">{{ trip.name }}</a>
      <span>Bookings</span>
    {% endbreadcrumbs %}

Each ``<a href>`` is a crumb with a link, each ``<span>`` one without (the last is the current page); a bare "/"
span is a separator and is dropped. The trail is hidden inside the trip page's item panel (``data-panel-hide``).
"""

import html
import re

from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

register = template.Library()

PIECE = re.compile(r'<a\s+[^>]*href="([^"]*)"[^>]*>(.*?)</a>|<span[^>]*>(.*?)</span>', re.S)
TAG = re.compile(r"<[^>]+>")


def crumbs_from(rendered):
    """[{"title", "url"}] from the rendered inside of the tag (titles are already escaped HTML)."""
    found = []
    for match in PIECE.finditer(rendered):
        url, linked, plain = match.groups()
        title = (linked if url is not None else plain) or ""
        if TAG.sub("", title).strip() in ("", "/"):
            continue
        found.append({"title": mark_safe(" ".join(title.split())), "url": html.unescape(url) if url else None})
    if found and found[-1]["url"]:
        found[-1]["keep_link"] = True  # the trail ends at the parent: keep it a link (the page has its own title)
    return found


class BreadcrumbsNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        crumbs = crumbs_from(self.nodelist.render(context))
        return render_to_string(
            "partials/_breadcrumbs.html", {"breadcrumbs": crumbs, "panel_hide": True}, request=context.get("request")
        )


@register.tag
def breadcrumbs(parser, token):
    nodelist = parser.parse(("endbreadcrumbs",))
    parser.delete_first_token()
    return BreadcrumbsNode(nodelist)
