"""
Feature registration for Campaigns app.
"""

from horilla.registry.feature import register_model_for_feature

register_model_for_feature(app_label="campaigns", model_name="Campaign", all=True)
