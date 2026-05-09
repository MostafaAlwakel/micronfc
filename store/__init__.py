from flask import Blueprint

store_bp = Blueprint(
    'store',
    __name__,
    template_folder='templates',
    url_prefix='/store'
)

from . import routes, dashboard
