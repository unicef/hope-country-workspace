from django import template

register = template.Library()


@register.filter
def workspace_urlname(value, arg):
    return "workspace:%s_%s_%s" % (value.app_label, value.model_name, arg)
