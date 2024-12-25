import firebase_admin
from firebase_admin import credentials, firestore
import os
import base64
import json

print("\n🔍 Starting Firebase Initialization...")

# Singleton pattern for Firebase initialization
if 'student_management_app' not in firebase_admin._apps:
    print("🔍 No existing app named 'student_management_app' found. Attempting to initialize...")

    try:
        # Decode Firebase credentials from the environment variable
        firebase_credentials_base64 = os.getenv("FIREBASE_CREDENTIALS")
        if not firebase_credentials_base64:
            raise ValueError("FIREBASE_CREDENTIALS environment variable is missing!")

        firebase_credentials_json = base64.b64decode(firebase_credentials_base64).decode('utf-8')
        firebase_credentials = json.loads(firebase_credentials_json)

        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(firebase_credentials)
        firebase_admin.initialize_app(cred, name='student_management_app')
        print("✅ Firebase initialized successfully.")

    except Exception as e:
        print(f"❌ Error initializing Firebase: {e}")
        raise

# Initialize Firestore
db = firestore.client()
print("✅ Firestore client initialized.")
