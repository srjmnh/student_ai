import re
import os
import json
import random
import logging
import base64
from flask import Flask, request, jsonify
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

###############################################################################
# 1. Flask Setup
###############################################################################
app = Flask(__name__, static_folder='static')

###############################################################################
# 2. Configure Logging
###############################################################################
# Configure logging to output to both console and a file
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

###############################################################################
# 3. Configure Gemini (Google Generative AI)
###############################################################################
# Embed your Gemini API Key directly into the code
GEMINI_API_KEY = "AIzaSyAtAewsF89BE6jPVMrgqWMWDXpmztao6eA"  # Replace with your actual Gemini API key
if not GEMINI_API_KEY:
    logging.error("GEMINI_API_KEY is not set.")
    raise ValueError("GEMINI_API_KEY is not set.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-1.5-flash")

###############################################################################
# 4. Initialize Firebase
###############################################################################
# Load Firebase credentials from environment variable
firebase_credentials_b64 = os.getenv('FIREBASE_CREDENTIALS')

if not firebase_credentials_b64:
    logging.error("FIREBASE_CREDENTIALS environment variable is not set.")
    raise EnvironmentError("FIREBASE_CREDENTIALS environment variable is not set.")

try:
    # Decode Base64 to JSON
    firebase_credentials_json = json.loads(
        base64.b64decode(firebase_credentials_b64).decode('utf-8')
    )
    # Initialize Firebase Admin SDK
    cred = credentials.Certificate(firebase_credentials_json)
    firebase_admin.initialize_app(cred, name='student_management_app')
    logging.info("✅ Firebase initialized!")
except Exception as e:
    logging.error(f"❌ Firebase initialization error: {e}")
    raise e

try:
    db = firestore.client(app=firebase_admin.get_app('student_management_app'))
    logging.info("✅ Firestore Client Initialized")
except Exception as e:
    logging.error(f"❌ Firestore client initialization error: {e}")
    raise e

###############################################################################
# 5. Conversation Memory & Activity Log
###############################################################################
conversation_memory = []
MAX_MEMORY = 20  # Increased memory size for better context

def save_memory_to_firestore():
    try:
        db.collection('conversation_memory').document('session_1').set({
            "memory": conversation_memory
        })
        logging.info("✅ Memory saved to Firestore.")
    except Exception as e:
        logging.error(f"❌ Failed to save memory: {e}")

def load_memory_from_firestore():
    try:
        doc = db.collection('conversation_memory').document('session_1').get()
        if doc.exists:
            logging.info("✅ Loaded conversation memory from Firestore.")
            return doc.to_dict().get("memory", [])
        logging.info("✅ No existing conversation memory found.")
        return []
    except Exception as e:
        logging.error(f"❌ Failed to load memory: {e}")
        return []

def log_activity(action_type, details):
    """
    Log each action (add/update/delete/view) to an 'activity_log' collection.
    """
    try:
        db.collection('activity_log').add({
            "action_type": action_type,
            "details": details,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        logging.info(f"✅ Logged activity: {action_type}, details={details}")
    except Exception as e:
        logging.error(f"❌ Failed to log activity: {e}")

###############################################################################
# 6. Student Logic (Add, Update, Delete, View)
###############################################################################
def generate_student_id(name, age):
    """Generate a unique student ID from the student's name & age."""
    random_number = random.randint(1000, 9999)
    name_part = (name[:4] if len(name) >= 4 else name).upper()
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def add_student(params):
    """
    Add a student with provided parameters. Only 'name' is mandatory.
    """
    try:
        name = params.get("name")
        age = params.get("age")
        class_name = params.get("class")
        address = params.get("address")
        phone = params.get("phone")
        guardian_name = params.get("guardian_name")
        guardian_phone = params.get("guardian_phone")
        attendance = params.get("attendance")
        grades = params.get("grades")

        if not name:
            logging.error("add_student: Missing mandatory field: name")
            return {"error": "Missing mandatory field: name"}, 400

        # Generate ID
        student_id = generate_student_id(name, age)

        # Prepare student data
        student_data = {
            "id": student_id,
            "name": name,
            "age": int(age) if age and age.isdigit() else None,
            "class": class_name,
            "address": address,
            "phone": phone,
            "guardian_name": guardian_name,
            "guardian_phone": guardian_phone,
            "attendance": attendance,
            "grades": grades
        }

        # Save to Firestore
        db.collection("students").document(student_id).set(student_data)
        logging.info(f"✅ Added student to Firestore: {student_data}")

        # Log the addition
        log_activity("ADD_STUDENT", f"Added {name} (ID {student_id}) with data: {student_data}")

        return {"message": f"Student {name} (ID: {student_id}) added successfully."}, 200

    except Exception as e:
        logging.error(f"❌ Error in add_student: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 7. Flask Routes
###############################################################################
@app.route("/")
def index():
    return jsonify({"message": "Welcome to the Student Management System!"})

@app.route("/add_student", methods=["POST"])
def add_student_route():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided."}), 400

        result, status = add_student(data)
        return jsonify(result), status
    except Exception as e:
        logging.error(f"❌ Error in /add_student: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 8. Run Flask on Port 8000
###############################################################################
if __name__ == "__main__":
    # Load existing conversation memory from Firestore
    conversation_memory = load_memory_from_firestore()
    app.run(debug=True, port=8000)
