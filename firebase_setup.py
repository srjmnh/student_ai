import firebase_admin
from firebase_admin import credentials, firestore
import os

print("\n🔍 Starting Firebase Initialization...")

# Singleton pattern for Firebase initialization
if 'student_management_app' not in firebase_admin._apps:
    print("🔍 No existing app named 'student_management_app' found. Attempting to initialize...")

    try:
        # Get the absolute path to the firebase_credentials.json
        current_path = os.path.dirname(os.path.abspath(__file__))
        cred_path = os.path.join(current_path, 'firebase_credentials.json')
        
        print(f"📁 Path to Credentials: {cred_path}")
        
        # Initialize Firebase app with a unique name
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, name='student_management_app')
        print("✅ Firebase successfully initialized for project: student-management-3009c")
    except Exception as e:
        print(f"❌ Failed to initialize Firebase: {e}")
else:
    print("ℹ️ Firebase app 'student_management_app' is already initialized.")

# Firestore Database
try:
    print("🔍 Attempting to get Firestore client...")
    db = firestore.client(app=firebase_admin.get_app('student_management_app'))
    print("✅ Firestore Client Initialized")
except Exception as e:
    print(f"❌ Failed to initialize Firestore client: {e}")