from flask import Blueprint

employee_bp = Blueprint('employee', __name__, template_folder='templates')

from app.blueprints.employee import routes
