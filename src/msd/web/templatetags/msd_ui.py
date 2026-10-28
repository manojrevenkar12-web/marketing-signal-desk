from django import template

from msd.conf import channel_label

register = template.Library()

KINDS = {"tracking_gap": "Tracking gap", "invalid_traffic": "Invalid traffic", "overreporting": "Over-reporting", "missing_days": "Missing days"}


@register.filter
def kind_label(kind: str) -> str:
    return KINDS.get(kind, kind.replace("_", " ").capitalize())


@register.filter
def channel(key: str | None) -> str:
    return channel_label(key) if key else "Every channel"
