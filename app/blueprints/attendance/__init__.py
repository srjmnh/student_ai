# app/blueprints/attendance/__init__.py

from flask import Blueprint

attendance_bp = Blueprint('attendance', __name__, template_folder='templates')

from . import routes