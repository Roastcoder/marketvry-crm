"""
Feature registration for Leads app.
"""

from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="leads",
    model_name="LeadStatus",
    features=["import_data", "export_data", "global_search"],
)

register_model_for_feature(app_label="leads", model_name="Lead", all=True)
