import os
import base64
import json

import firebase_admin
from firebase_admin import credentials, firestore

APP_NAME = "student_management_app"

def get_firestore_client():
    """
    Initialize or retrieve a Firebase app using Base64-encoded credentials
    from the FIREBASE_CREDENTIALS environment variable, and return a Firestore client.
    """
    # 1. Load the base64-encoded JSON from environment variable
    firebase_credentials_base64 = os.getenv("FIREBASE_CREDENTIALS")
    if not firebase_credentials_base64:
        raise ValueError("FIREBASE_CREDENTIALS environment variable is missing or empty!")

    # 2. Decode Base64 → JSON
    try:
        firebase_credentials_json = base64.b64decode(firebase_credentials_base64).decode("utf-8")
        firebase_credentials = json.loads(firebase_credentials_json)
    except Exception as e:
        raise ValueError(f"Failed to decode FIREBASE_CREDENTIALS Base64 data: {e}")

    # 3. Initialize the named Firebase app if it's not already initialized
    if APP_NAME not in firebase_admin._apps:
        print(f"\n[Firebase Setup] No existing app named '{APP_NAME}' found. Initializing...")
        try:
            cred = credentials.Certificate(firebase_credentials)
            firebase_admin.initialize_app(cred, name=APP_NAME)
            print("[Firebase Setup] ✅ Firebase app initialized successfully.")
        except Exception as e:
            print(f"[Firebase Setup] ❌ Error initializing Firebase: {e}")
            raise
    else:
        print(f"\n[Firebase Setup] Firebase app '{APP_NAME}' is already initialized.")

    # 4. Return a Firestore client for this app
    try:
        db = firestore.client(app=firebase_admin.get_app(APP_NAME))
        print("[Firebase Setup] ✅ Firestore client initialized.\n")
        return db
    except Exception as e:
        raise ValueError(f"Failed to initialize Firestore: {str(e)}")
