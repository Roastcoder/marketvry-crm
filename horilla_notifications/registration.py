"""
This module is responsible for registering the notification template feature in the Horilla framework. It imports the necessary function to register the feature and then registers the "notification_template" feature with its corresponding models."
"""

from horilla.registry.feature import register_feature

register_feature("notification_template", "notification_template_models")
