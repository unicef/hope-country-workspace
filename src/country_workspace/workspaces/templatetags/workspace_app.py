from django.template import Library

from country_workspace import VERSION

register = Library()


@register.simple_tag
def app_version() -> str:
    return VERSION
