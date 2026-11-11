from django import template

from newsletter import services
from newsletter.models import NewsGroup, Post

register = template.Library()

SIDEBAR_GROUPS = 25
SIDEBAR_PINNED = 8


@register.inclusion_tag("newsletter/_sidebar.html", takes_context=True)
def news_sidebar(context):
    """Right-hand sidebar of every newsletter page: 1) Groups  2) Pinned. Server-side filtered per viewer."""
    user = context["request"].user
    signed_in = user.is_authenticated
    groups, states, group_total = [], {}, 0
    if signed_in:
        qs = NewsGroup.objects.select_related("manager")
        group_total = qs.count()
        groups = list(qs[:SIDEBAR_GROUPS])
        states = services.group_states(user, groups)
        for g in groups:
            g.state = states.get(g.pk)
    pinned = list(
        Post.objects.visible_to(user).filter(is_pinned=True).select_related("group").order_by("-created_at")[:SIDEBAR_PINNED]
    )
    return {
        "request": context["request"], "viewer": user, "signed_in": signed_in, "groups": groups, "group_total": group_total,
        "more_groups": max(group_total - len(groups), 0), "pinned": pinned,
    }
