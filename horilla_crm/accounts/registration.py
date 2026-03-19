"""
Feature registration for Accounts app.
"""

from horilla.registry.feature import register_model_for_feature

register_model_for_feature(app_label="accounts", model_name="Account", all=True)
