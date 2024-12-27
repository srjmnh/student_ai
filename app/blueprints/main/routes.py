# app/blueprints/main/routes.py

from flask import render_template, current_app

@main_bp.route('/')
def index():
    # Optionally, fetch data to display on the home page
    return render_template('index.html')