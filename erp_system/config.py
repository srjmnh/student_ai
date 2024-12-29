import os

class Config:
    # Firebase Configurations
    FIREBASE_CREDENTIALS = os.environ.get('FIREBASE_CREDENTIALS') or 'path/to/your/firebase_credentials.json'
    
    # Gemini AI Configurations
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or 'your_gemini_api_key_here'
    
    # Additional Configurations
    # e.g., database URI if using another DB
