"""
Admin registration for the horilla_automations app
"""

from django.contrib import admin

from horilla_automations.models import AutomationCondition, HorillaAutomation

# Register your horilla_automations models here.

admin.site.register(HorillaAutomation)
admin.site.register(AutomationCondition)
