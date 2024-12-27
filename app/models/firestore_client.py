# app/models/firestore_client.py

import os
import json
import base64
import firebase_admin
from firebase_admin import credentials, firestore

def init_firestore():
    if not firebase_admin._apps:
        encoded_json = os.getenv("FIREBASE_CREDENTIALS")
        if not encoded_json:
            raise EnvironmentError("FIREBASE_CREDENTIALS not set or empty.")
        try:
            decoded_json = base64.b64decode(encoded_json).decode('utf-8')
            service_account_info = json.loads(decoded_json)
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred, name='student_management_app')
        except Exception as e:
            raise Exception(f"Error initializing Firebase: {e}")
    return firestore.client(app=firebase_admin.get_app('student_management_app'))