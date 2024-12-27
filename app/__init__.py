# app/__init__.py

from flask import Flask
from .config import Config
from .models.firestore_client import init_firestore
import google.generativeai as genai

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Config.init_app(app)
    
    # Initialize Firestore
    db = init_firestore()
    
    # Configure Gemini (Google Generative AI)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        app.logger.error("GEMINI_API_KEY environment variable not set.")
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    
    # Make db and model accessible in blueprints
    app.db = db
    app.model = model
    
    # Register Blueprints
    from .blueprints.students import students_bp
    from .blueprints.attendance import attendance_bp
    from .blueprints.grades import grades_bp
    from .blueprints.auth import auth_bp
    
    app.register_blueprint(students_bp, url_prefix='/students')
    app.register_blueprint(attendance_bp, url_prefix='/attendance')
    app.register_blueprint(grades_bp, url_prefix='/grades')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    # Main route
    from .blueprints.main import main_bp
    app.register_blueprint(main_bp)
    
    return app