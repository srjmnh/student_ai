# app/blueprints/grades/__init__.py

from flask import Blueprint

grades_bp = Blueprint('grades', __name__, template_folder='templates')

from . import routes