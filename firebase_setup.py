import base64
import json
import os
from firebase_admin import credentials, firestore

# Decode Firebase credentials from the environment variable
firebase_credentials_b64 = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_credentials_b64:
    raise EnvironmentError("FIREBASE_CREDENTIALS environment variable is not set.")

try:
    firebase_credentials_json = json.loads(
        base64.b64decode(firebase_credentials_b64).decode("utf-8")
    )
    cred = credentials.Certificate(firebase_credentials_json)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase initialized successfully!")
except Exception as e:
    print(f"❌ Error initializing Firebase: {e}")
    raise
