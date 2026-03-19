"""
Horilla generics views package.

Aggregates generic list, detail, form, kanban, group-by, and helper views.
Import order is significant to avoid circular imports.
"""

from horilla_generics.views.core import *
from horilla_generics.views.delete import *
from horilla_generics.views.helpers.condition_widget import *
from horilla_generics.views.details import *
from horilla_generics.views.list import *
from horilla_generics.views.card import *
from horilla_generics.views.split_view import *
from horilla_generics.views.detail_tabs import *
from horilla_generics.views.groupby import *
from horilla_generics.views.chart import *
from horilla_generics.views.kanban import *
from horilla_generics.views.timeline import *
from horilla_generics.views import helpers
from horilla_generics.views.attachments import *
from horilla_generics.views.global_search import *
from horilla_generics.views.related_list import *
from horilla_generics.views.single_form import *
from horilla_generics.views.multi_form import *
from horilla_generics.views.navbar import *
