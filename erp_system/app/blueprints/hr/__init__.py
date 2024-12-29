from flask import Blueprint

hr_bp = Blueprint('hr', __name__, template_folder='templates')

from app.blueprints.hr import routes
