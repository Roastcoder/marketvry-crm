"""
Template filters for horilla_dashboard templates.

Provides simple filter helpers to narrow dashboard components by type.
"""

from django import template

register = template.Library()


@register.filter
def filter_by_type(queryset, component_type):
    """Filter queryset by component type"""
    return queryset.filter(component_type=component_type)


@register.filter
def filter_by_type_exclude(queryset, component_type):
    """Exclude components of specified type from queryset"""
    return queryset.exclude(component_type=component_type)
