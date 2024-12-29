from flask import Flask
from config import Config
from app.firestore_client import get_firestore_client
from app.gemini_integration import GeminiIntegration
import logging
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize CORS
    CORS(app, resources={r"/*": {"origins": "*"}})  # Adjust origins as needed for production
    
    # Initialize Firestore Client
    app.db = get_firestore_client(app.config['FIREBASE_CREDENTIALS'])
    
    # Initialize Gemini AI Integration
    app.gemini = GeminiIntegration(app)
    
    # Set up Logging
    logging.basicConfig(level=logging.INFO)
    
    # Register Blueprints
    from app.blueprints.auth import auth_bp
    from app.blueprints.hr import hr_bp
    from app.blueprints.employee import employee_bp
    from app.blueprints.main import main_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(hr_bp, url_prefix='/hr')
    app.register_blueprint(employee_bp, url_prefix='/employee')
    app.register_blueprint(main_bp)
    
    return app