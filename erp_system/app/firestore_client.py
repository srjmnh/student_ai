import firebase_admin
from firebase_admin import credentials, firestore
import logging

def get_firestore_client(credentials_path):
    try:
        cred = credentials.Certificate(credentials_path)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("✅ Firestore client initialized successfully.")
        return db
    except Exception as e:
        logging.error(f"❌ Error initializing Firestore client: {e}")
        raise