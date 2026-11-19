"""``{% filter_bar %}…{% endfilter_bar %}`` (ux-consistency V2): every list page's filters in one shape
(``partials/_filter_bar.html``): a card, the fields written inside the tag in one grid, applied as soon as a select
or tick box changes, a Go button (Enter in the search box, and the way without JavaScript), a Clear link while any
filter is set, and the result count.

    {% load filter_tags %}
    {% filter_bar count=page_obj.paginator.count ignore="sort when" keep="activity" %}
      <div><label class="sbl-label" for="q">Search</label><input id="q" name="q" class="sbl-input" …></div>
      …
    {% endfilter_bar %}

``count`` — the number of results (left out: no count); ``ignore`` — parameters that don't make the list "filtered"
(sort order, a select that always has a value); ``keep`` — parameters Clear keeps (the page's context, like the
activity whose dates these are). ``page`` never counts and is never kept.
"""

from urllib.parse import urlencode

from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

register = template.Library()


class FilterBarNode(template.Node):
    def __init__(self, nodelist, options):
        self.nodelist = nodelist
        self.options = options

    def render(self, context):
        options = {name: value.resolve(context) for name, value in self.options.items()}
        request = context.get("request")
        query = request.GET if request is not None else {}
        ignore = set((options.get("ignore") or "").split()) | {"page"}
        keep = set((options.get("keep") or "").split())
        active = any(value for name, value in query.items() if name not in ignore and name not in keep)
        kept = {name: query.get(name) for name in keep if query.get(name)}
        clear_url = (request.path if request is not None else "") + (f"?{urlencode(kept)}" if kept else "")
        return render_to_string(
            "partials/_filter_bar.html",
            {
                "fields": mark_safe(self.nodelist.render(context)),
                "count": options.get("count"),
                "active": active,
                "clear_url": clear_url,
            },
            request=request,
        )


@register.tag
def filter_bar(parser, token):
    options = {}
    for bit in token.split_contents()[1:]:
        name, _, value = bit.partition("=")
        if not value:
            raise template.TemplateSyntaxError(f"filter_bar takes name=value options, not {bit!r}")
        options[name] = parser.compile_filter(value)
    nodelist = parser.parse(("endfilter_bar",))
    parser.delete_first_token()
    return FilterBarNode(nodelist, options)
