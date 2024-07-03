import hashlib
import itertools

from django.template import Library

register = Library()

COLORS = ["blue", "red", "gray", "green", "yellow", "indigo", "purple"]

infinite = itertools.cycle(COLORS)


@register.simple_tag()
def random_color() -> str:
    return next(infinite)


@register.filter()
def color(value: str) -> str:
    h = hashlib.md5(value.encode()).hexdigest()
    c = str(bin(int(h, 16))[2:])
    ci = sum(int(x) for x in c)
    return COLORS[ci % len(COLORS)]
