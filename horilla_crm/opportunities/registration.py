"""
Feature registration for Opportunities app.
"""

from horilla.registry.feature import register_model_for_feature

register_model_for_feature(
    app_label="opportunities",
    model_name="OpportunityStage",
    features=["import_data", "export_data", "global_search"],
)

register_model_for_feature(
    app_label="opportunities", model_name="Opportunity", all=True
)

register_model_for_feature(
    app_label="opportunities", model_name="OpportunityTeam", features=["global_search"]
)

register_model_for_feature(
    app_label="opportunities",
    model_name="OpportunitySplit",
    features=["report_choices"],
)
