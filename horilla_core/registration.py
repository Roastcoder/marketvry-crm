"""
Feature registration for Horilla Core app.
"""

from horilla.auth.models import User
from horilla.registry.feature import register_feature, register_models_for_feature
from horilla_core.models import Company, Department, Role

register_models_for_feature(
    models=[
        Company,
        Department,
        Role,
        User,
    ],
    all=True,
    exclude=["dashboard_component", "report_choices"],
)


register_feature(
    "template_reverse",
    "template_reverse_models",
    auto_register_all=True,
    include_models=[
        ("horilla_core", "company"),
        ("horilla_core", "department"),
        ("horilla_core", "role"),
        ("horilla_core", "horillauser"),
    ],
)
