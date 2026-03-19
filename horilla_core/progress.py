"""Progress tracking mixin for multi-step workflows.

This module provides a mixin class for tracking progress through multi-step
processes, particularly used during database initialization workflows.
"""

from copy import deepcopy

BASE_STEPS = [
    {"step": 1, "title": "Database authentication"},
    {"step": 2, "title": "Sign Up"},
    {"step": 3, "title": "Company Info"},
    {"step": 4, "title": "Role"},
]


class ProgressStepsMixin:
    """Mixin to track and display progress through multi-step workflows.

    This mixin provides methods to manage progress indicators for step-by-step
    processes. It tracks the current step and provides utilities to determine
    step states and whether the current step is the last one.
    """

    current_step = 1  # override in each view

    def get_progress_steps(self):
        """
        Get progress steps with active status based on current step.

        Returns:
            list: List of step dictionaries, each containing:
                - step: Step number
                - title: Step title
                - active: Boolean indicating if step is active (completed or current)
        """
        steps = deepcopy(BASE_STEPS)  # avoid modifying global list
        for step in steps:
            step["active"] = step["step"] <= self.current_step
        return steps

    def is_last_step(self):
        """
        Check if the current step is the last step in the workflow.

        Returns:
            bool: True if current step is the last step, False otherwise.
        """
        return self.current_step == BASE_STEPS[-1]["step"]
