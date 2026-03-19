"""
Feature registration for Contacts app.
"""

from horilla.registry.feature import register_model_for_feature

register_model_for_feature(app_label="contacts", model_name="Contact", all=True)
