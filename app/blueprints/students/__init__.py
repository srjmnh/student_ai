# app/blueprints/students/__init__.py

from flask import Blueprint

students_bp = Blueprint('students', __name__, template_folder='templates')

from . import routes