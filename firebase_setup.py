import os
import base64
import json
from firebase_admin import credentials, initialize_app

# Decode and load Firebase credentials from the environment variable
firebase_credentials_base64 = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_credentials_base64:
    raise ValueError("FIREBASE_CREDENTIALS environment variable is missing!")

try:
    # Decode Base64 to JSON
    firebase_credentials_json = base64.b64decode(firebase_credentials_base64).decode('utf-8')
    firebase_credentials = json.loads(firebase_credentials_json)

    # Initialize Firebase Admin SDK using the JSON object
    cred = credentials.Certificate(firebase_credentials)
    initialize_app(cred)
    print("✅ Firebase initialized successfully.")

except Exception as e:
    raise ValueError(f"Failed to initialize Firebase: {str(e)}")
