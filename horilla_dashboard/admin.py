"""Admin configuration for dashboard app."""

from django.contrib import admin

from .models import (
    ComponentCriteria,
    Dashboard,
    DashboardComponent,
    DashboardFolder,
    DefaultHomeLayoutOrder,
)

# Register your dashboard models here.
admin.site.register(Dashboard)
admin.site.register(DashboardComponent)
admin.site.register(ComponentCriteria)
admin.site.register(DashboardFolder)
admin.site.register(DefaultHomeLayoutOrder)
