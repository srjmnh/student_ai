import re
import os
import json
import random
import logging
import base64
from flask import Flask, request, jsonify

# Google Generative AI
import google.generativeai as genai

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

###############################################################################
# 1. Flask Setup
###############################################################################
app = Flask(__name__)

###############################################################################
# 2. Configure Logging
###############################################################################
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

genai.configure(api_key=GEMINI_API_KEY)
# If you do NOT have access to Gemini, switch to "models/chat-bison-001"
model = genai.GenerativeModel("models/gemini-1.5-flash")

###############################################################################
# 4. Firebase Initialization (Base64 credentials)
###############################################################################
if 'student_management_app' not in firebase_admin._apps:
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

db = firestore.client(app=firebase_admin.get_app('student_management_app'))
logging.info("✅ Firebase and Firestore initialized successfully.")

###############################################################################
# 5. Conversation + State + Memory
###############################################################################
conversation_memory = []
MAX_MEMORY = 20
welcome_summary = ""

# States
STATE_IDLE = "IDLE"
STATE_AWAITING_STUDENT_INFO = "AWAITING_STUDENT_INFO"
STATE_AWAITING_ANALYTICS_TARGET = "AWAITING_ANALYTICS_TARGET"

conversation_context = {
    "state": STATE_IDLE,
    "pending_params": {},
    "last_intended_action": None
}

def save_memory_to_firestore():
    try:
        db.collection('conversation_memory').document('session_1').set({
            "memory": conversation_memory,
            "context": conversation_context
        })
        logging.info("✅ Memory saved to Firestore.")
    except Exception as e:
        logging.error(f"❌ Failed to save memory: {e}")

def load_memory_from_firestore():
    try:
        doc = db.collection('conversation_memory').document('session_1').get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("memory", []), data.get("context", {})
        return [], {}
    except Exception as e:
        logging.error(f"❌ Failed to load memory: {e}")
        return [], {}

def log_activity(action_type, details):
    try:
        db.collection('activity_log').add({
            "action_type": action_type,
            "details": details,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logging.error(f"❌ Failed to log activity: {e}")

###############################################################################
# 6. Generate Comedic Summary
###############################################################################
def generate_comedic_summary_of_past_activities():
    try:
        logs = db.collection('activity_log').order_by('timestamp').limit(100).stream()
        activity_lines = []
        for log_doc in logs:
            data = log_doc.to_dict()
            action_type = data.get("action_type")
            details = data.get("details")
            activity_lines.append(f"{action_type}: {details}")

        if not activity_lines:
            return "Strangely quiet. No records of past deeds... yet."

        combined = "\n".join(activity_lines)
        prompt = (
            "As a darkly humorous AI, provide a concise (under 50 words) summary "
            "of these student management actions. Maintain a grim yet witty tone.\n\n"
            f"{combined}"
        )
        resp = model.generate_content(prompt)
        if resp.candidates:
            summary = resp.candidates[0].content.parts[0].text.strip()
            return summary
        else:
            return "No comedic summary conjured. The silence is deafening."
    except Exception as e:
        logging.error(f"❌ Error generating comedic summary: {e}")
        return "An error occurred while digging up the past activities..."

###############################################################################
# 7. Utility: remove code fences
###############################################################################
def remove_code_fences(text: str) -> str:
    fenced_pattern = r'^```(?:json)?\s*([\s\S]*?)\s*```$'
    match = re.match(fenced_pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text

###############################################################################
# 8. Firestore Helper Functions
###############################################################################
def _safe_int(value):
    """
    Attempt to parse value as int. If it's already int, use it.
    If it fails, return None (avoid 'int' object has no attribute 'isdigit').
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

def generate_student_id(name, age):
    random_number = random.randint(1000, 9999)
    name_part = (name[:4] if len(name) >= 4 else name).upper()
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def create_funny_prompt_for_new_student(name):
    return (
        f"Write a short witty statement acknowledging we have a new student '{name}'. "
        "Ask the user if they have any additional details they'd like to add, such as marks or attendance. "
        "Keep it under 40 words, with a slightly humorous twist."
    )

def create_comedic_confirmation(action, name=None, student_id=None):
    if action == "add_student":
        prompt = f"Generate a short, darkly funny success message confirming the addition of {name} (ID: {student_id})."
    elif action == "update_student":
        prompt = f"Create a short, darkly funny message confirming the update of student ID {student_id}."
    elif action == "delete_student":
        prompt = f"Create a short, darkly funny message confirming the deletion of student ID {student_id}."
    else:
        prompt = "A cryptic success message with an ominous twist."

    resp = model.generate_content(prompt)
    if resp.candidates:
        return resp.candidates[0].content.parts[0].text.strip()[:100]
    else:
        return "Action completed, presumably in a dark fashion."

###############################################################################
# 9. Cleanup Data (Deduplicate by Name)
###############################################################################
def cleanup_data():
    """
    Finds duplicates by 'name', keeps the most detailed doc, deletes others.
    Returns an HTML snippet with the updated table.
    """
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    from collections import defaultdict
    name_groups = defaultdict(list)

    for st in students:
        st_name = st.get("name", "").strip().lower()
        if st_name:
            name_groups[st_name].append(st)

    duplicates_deleted = []
    for _, group in name_groups.items():
        if len(group) > 1:
            # Keep doc with the greatest number of non-empty fields
            best_student = None
            best_score = -1
            for st in group:
                score = sum(1 for v in st.values() if v not in [None, "", {}])
                if score > best_score:
                    best_score = score
                    best_student = st
            # Delete all others
            for st in group:
                if st["id"] != best_student["id"]:
                    db.collection("students").document(st["id"]).delete()
                    duplicates_deleted.append(st["id"])

    if duplicates_deleted:
        log_activity("CLEANUP_DATA", f"Deleted duplicates: {duplicates_deleted}")

    # Return updated table with "Data cleaned!"
    return build_students_table_html("Data cleaned! Updated student records below:")

###############################################################################
# 10. Building a Table that Slides in from Right
###############################################################################
def build_students_table_html(heading="Student Records"):
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    if not students:
        return "<p>No students found.</p>"

    html = f"""
<div id="studentsSection" class="slideFromRight">
  <h4>{heading}</h4>
  <table class="table table-bordered">
    <thead class="table-light">
      <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Age</th>
        <th>Class</th>
        <th>Address</th>
        <th>Phone</th>
        <th>Guardian</th>
        <th>Guardian Phone</th>
        <th>Attendance</th>
        <th>Grades</th>
      </tr>
    </thead>
    <tbody>
    """
    for st in students:
        row = f"""
        <tr>
          <td>{st.get('id','')}</td>
          <td>{st.get('name','')}</td>
          <td>{st.get('age','')}</td>
          <td>{st.get('class','')}</td>
          <td>{st.get('address','')}</td>
          <td>{st.get('phone','')}</td>
          <td>{st.get('guardian_name','')}</td>
          <td>{st.get('guardian_phone','')}</td>
          <td>{st.get('attendance','')}</td>
          <td>{st.get('grades','')}</td>
        </tr>
        """
        html += row
    html += """
    </tbody>
  </table>
  <button class="btn btn-success" onclick="saveTableEdits()">Save</button>
</div>
"""
    return html

###############################################################################
# 11. View Students (Simple Table)
###############################################################################
def view_students_table():
    """
    For the 'view_students' action (or synonyms), we just build the table with default heading.
    """
    return build_students_table_html("Student Records")

###############################################################################
# 12. Student Logic (Add, Update, Delete, Analytics)
###############################################################################
def add_student(params):
    try:
        name = params.get("name")
        if not name:
            return {"error": "Missing 'name' to add student."}, 400

        age = _safe_int(params.get("age"))
        sclass = params.get("class")
        address = params.get("address")
        phone = params.get("phone")
        guardian_name = params.get("guardian_name")
        guardian_phone = params.get("guardian_phone")
        attendance = params.get("attendance")
        grades = params.get("grades") or {}

        student_id = generate_student_id(name, age)
        student_data = {
            "id": student_id,
            "name": name,
            "age": age,
            "class": sclass,
            "address": address,
            "phone": phone,
            "guardian_name": guardian_name,
            "guardian_phone": guardian_phone,
            "attendance": attendance,
            "grades": grades,
            "grades_history": []
        }

        db.collection("students").document(student_id).set(student_data)
        log_activity("ADD_STUDENT", f"Added {name} (ID {student_id}).")

        confirmation = create_comedic_confirmation("add_student", name, student_id)
        return {"message": f"{confirmation} (ID: {student_id})"}, 200

    except Exception as e:
        logging.error(f"❌ Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing student 'id' for update."}, 400

        doc_ref = db.collection("students").document(student_id)
        doc_snapshot = doc_ref.get()
        if not doc_snapshot.exists:
            return {"error": f"No student with id {student_id} found."}, 404

        update_fields = {}
        for k, v in params.items():
            if k != "id":
                update_fields[k] = v

        # If user is updating 'grades', store old in 'grades_history'
        if "grades" in update_fields:
            existing_data = doc_snapshot.to_dict()
            old_grades = existing_data.get("grades", {})
            new_grades_entry = {
                "old_grades": old_grades,
                "new_grades": update_fields["grades"],
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            if "grades_history" not in existing_data:
                existing_data["grades_history"] = []
            existing_data["grades_history"].append(new_grades_entry)
            update_fields["grades_history"] = existing_data["grades_history"]

        doc_ref.update(update_fields)
        log_activity("UPDATE_STUDENT", f"Updated {student_id} with {update_fields}")

        confirmation = create_comedic_confirmation("update_student", student_id=student_id)
        return {"message": confirmation}, 200

    except Exception as e:
        logging.error(f"❌ Error in update_student: {e}")
        return {"error": str(e)}, 500

def delete_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing student 'id' for deletion."}, 400

        doc_ref = db.collection("students").document(student_id)
        if not doc_ref.get().exists:
            return {"error": f"No student with id {student_id} found."}, 404

        doc_ref.delete()
        log_activity("DELETE_STUDENT", f"Deleted student ID {student_id}")

        confirmation = create_comedic_confirmation("delete_student", student_id=student_id)
        return {"message": confirmation}, 200

    except Exception as e:
        logging.error(f"❌ Error in delete_student: {e}")
        return {"error": str(e)}, 500

def analytics_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing 'id' to analyze student."}, 400

        doc_snapshot = db.collection("students").document(student_id).get()
        if not doc_snapshot.exists:
            return {"error": f"No student with id {student_id} found."}, 404

        data = doc_snapshot.to_dict()
        grades_history = data.get("grades_history", [])
        if len(grades_history) < 1:
            return {"message": f"No historical grades found for {data['name']}."}, 200

        def avg_marks(grades):
            if not grades:
                return 0
            vals = [v for v in grades.values() if isinstance(v, (int, float))]
            return sum(vals) / len(vals) if vals else 0

        oldest = grades_history[0]["old_grades"]
        newst = grades_history[-1]["new_grades"]
        old_avg = avg_marks(oldest)
        new_avg = avg_marks(newst)
        trend = "improved" if new_avg > old_avg else "declined" if new_avg < old_avg else "stayed the same"

        message = f"{data['name']}'s performance has {trend}. Old avg={old_avg:.2f}, new avg={new_avg:.2f}."
        return {"message": message}, 200

    except Exception as e:
        logging.error(f"❌ Error in analytics_student: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 13. Simple Classification for "Casual" vs. "Firestore"
###############################################################################
def classify_casual_or_firestore(user_prompt):
    """
    Use Gemini to decide if the user prompt is a casual conversation
    or a Firestore action.
    We'll return JSON like:
    {
      "type": "casual"
    }
    or
    {
      "type": "firestore",
      "action": "add_student",
      "parameters": {...}
    }
    If it can't parse, we treat it as casual.
    """
    classification_prompt = (
        "You are an advanced assistant that ONLY decides if a user request is "
        "casual conversation or Firestore action.\n\n"
        "If casual, return: {\"type\":\"casual\"}\n"
        "If firestore, return a JSON object with \"type\":\"firestore\", an \"action\" key, and a \"parameters\" object.\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student.\n"
        "Synonyms:\n"
        "- 'view students', 'show all students', 'list students' => view_students\n"
        "- 'cleanup data', 'clean data', 'deduplicate' => cleanup_data\n"
        "- 'performance', 'check performance' => analytics_student\n"
        "- 'hire students' => view_students\n\n"
        f"User Prompt: '{user_prompt}'\n"
        "Output JSON only, no code fences."
    )
    resp = model.generate_content(classification_prompt)
    if not resp.candidates:
        return {"type": "casual"}

    raw = resp.candidates[0].content.parts[0].text.strip()
    raw = remove_code_fences(raw)
    try:
        data = json.loads(raw)
        # Force "type" if missing
        if "type" not in data:
            data["type"] = "casual"
        return data
    except (json.JSONDecodeError, ValueError):
        return {"type": "casual"}

###############################################################################
# 14. Additional Field Extraction, Analytics Handler
###############################################################################
def extract_fields(user_input, desired_fields):
    prompt = (
        f"You are an assistant that extracts fields from user input. "
        f"Fields: {', '.join(desired_fields)}.\n"
        f"User Input: '{user_input}'\n\n"
        "Return JSON with only these fields if found. No code fences."
    )
    resp = model.generate_content(prompt)
    if resp.candidates:
        content = ''.join(part.text for part in resp.candidates[0].content.parts).strip()
        content = remove_code_fences(content)
        try:
            return json.loads(content)
        except:
            return {}
    return {}

def handle_analytics_call(params):
    if params.get("id"):
        result, status = analytics_student(params)
        return result.get("message", result.get("error", "Analytics error."))
    elif params.get("name"):
        docs = db.collection("students").where("name", "==", params["name"]).stream()
        matches = [d.to_dict() for d in docs]
        if not matches:
            return f"No student found with name {params['name']}."
        if len(matches) == 1:
            params["id"] = matches[0]["id"]
            result, status = analytics_student(params)
            return result.get("message", result.get("error", "Analytics error."))
        else:
            listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
            return f"Multiple students named {params['name']} found:\n{listing}\nWhich ID do you want to analyze?"
    else:
        return "Which student do you want to check performance for? Provide an ID or name."

###############################################################################
# 15. The Main State Machine: Decide Casual or Firestore
###############################################################################
def handle_state_machine(user_prompt):
    # 1) Check if we are in a partial-add or partial-analytics scenario
    state = conversation_context["state"]
    pending_params = conversation_context["pending_params"]

    if state == STATE_AWAITING_STUDENT_INFO:
        desired_fields = ["name", "age", "class", "address", "phone", "guardian_name", "guardian_phone", "attendance", "grades"]
        extracted = extract_fields(user_prompt, desired_fields)
        for k, v in extracted.items():
            pending_params[k] = v

        if not pending_params.get("name"):
            return "I still need the student's name. Provide it or say 'cancel' to stop."

        result, status = add_student(pending_params)
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None

        if "message" in result and status == 200:
            # comedic follow-up
            funny_prompt = create_funny_prompt_for_new_student(pending_params["name"])
            followup_resp = model.generate_content(funny_prompt)
            if followup_resp.candidates:
                followup_text = followup_resp.candidates[0].content.parts[0].text.strip()
                return result["message"] + "\n\n" + followup_text
            else:
                return result["message"]
        else:
            return result.get("error", "Error adding student.")

    elif state == STATE_AWAITING_ANALYTICS_TARGET:
        desired_fields = ["id", "name"]
        extracted = extract_fields(user_prompt, desired_fields)
        for k, v in extracted.items():
            pending_params[k] = v

        if pending_params.get("id"):
            result, status = analytics_student(pending_params)
            conversation_context["state"] = STATE_IDLE
            conversation_context["pending_params"] = {}
            conversation_context["last_intended_action"] = None
            return result.get("message", result.get("error", "Analytics error."))

        elif pending_params.get("name"):
            docs = db.collection("students").where("name", "==", pending_params["name"]).stream()
            matches = [d.to_dict() for d in docs]
            if not matches:
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return f"No student found with name {pending_params['name']}."
            if len(matches) == 1:
                pending_params["id"] = matches[0]["id"]
                result, status = analytics_student(pending_params)
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return result.get("message", result.get("error", "Analytics error."))
            else:
                listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
                return f"Multiple students named {pending_params['name']} found:\n{listing}\nWhich ID do you want to analyze?"
        else:
            return "Which student do you want to check? Provide an ID or name."

    else:
        # 2) We are IDLE, so let's ask Gemini if it's casual or firestore
        classification_result = classify_casual_or_firestore(user_prompt)
        if classification_result.get("type") == "casual":
            # Just respond casually
            resp = model.generate_content(user_prompt)
            if resp.candidates:
                return resp.candidates[0].content.parts[0].text.strip()
            else:
                return "I'm at a loss for words..."

        elif classification_result.get("type") == "firestore":
            action = classification_result.get("action", "")
            params = classification_result.get("parameters", {})

            # we handle synonyms ourselves if needed, or rely on Gemini to get it right
            # Check which action:
            if action == "view_students":
                return build_students_table_html("Student Records")

            elif action == "cleanup_data":
                return cleanup_data()

            elif action == "add_student":
                if not params.get("name"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = params
                    conversation_context["last_intended_action"] = "add_student"
                    return "Let's add a new student. What's their name?"
                else:
                    result, status = add_student(params)
                    if status == 200 and "message" in result:
                        funny_prompt = create_funny_prompt_for_new_student(params["name"])
                        followup_resp = model.generate_content(funny_prompt)
                        if followup_resp.candidates:
                            followup_text = followup_resp.candidates[0].content.parts[0].text.strip()
                            return result["message"] + "\n\n" + followup_text
                        else:
                            return result["message"]
                    else:
                        return result.get("error", "Add student error.")

            elif action == "update_student":
                if not params.get("id"):
                    return "To update a student, provide 'id'."
                else:
                    result, status = update_student(params)
                    return result.get("message", result.get("error", "Update error."))

            elif action == "delete_student":
                if not params.get("id"):
                    return "To delete a student, provide 'id'."
                else:
                    result, status = delete_student(params)
                    return result.get("message", result.get("error", "Delete error."))

            elif action == "analytics_student":
                if not (params.get("id") or params.get("name")):
                    conversation_context["state"] = STATE_AWAITING_ANALYTICS_TARGET
                    conversation_context["pending_params"] = params
                    conversation_context["last_intended_action"] = "analytics_student"
                    return "Which student do you want to check performance for? Provide an ID or name."
                else:
                    return handle_analytics_call(params)

            else:
                return f"Unknown Firestore action: {action}"

        else:
            # If classification result is missing or incomplete
            return "I'm not sure what you're asking. Is this casual conversation or a database action?"

###############################################################################
# 16. Flask Routes
###############################################################################
@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Super Student Management Chat</title>

  <link 
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" 
    rel="stylesheet"
  />

  <style>
    body {
      background-color: #f8f9fa;
      font-family: "Helvetica Neue", Arial, sans-serif;
      margin: 0;
      padding: 0;
    }

    .chat-container {
      max-width: 700px;
      margin: 2rem auto;
      background-color: #fff;
      border-radius: 0.5rem;
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
      display: flex;
      flex-direction: column;
      height: 80vh; /* 80% of the viewport height */
      overflow: hidden;
    }

    .chat-header {
      background-color: #343a40;
      color: #fff;
      padding: 1rem;
      text-align: center;
    }

    .chat-body {
      flex: 1;
      padding: 1rem;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }

    .chat-bubble {
      padding: 0.75rem 1rem;
      margin-bottom: 0.75rem;
      border-radius: 15px;
      max-width: 75%;
      word-wrap: break-word;
      white-space: pre-wrap;
    }

    .user-message {
      background-color: #007bff;
      color: #fff;
      align-self: flex-end;
      border-bottom-right-radius: 0;
    }

    .ai-message {
      background-color: #e9ecef;
      color: #000;
      align-self: flex-start;
      border-bottom-left-radius: 0;
    }

    .ai-message table {
      width: 100%;
      margin-top: 0.5rem;
      border: 1px solid #ccc;
      border-collapse: collapse;
    }
    .ai-message th, .ai-message td {
      border: 1px solid #ccc;
      padding: 0.5rem;
      text-align: left;
    }
    .ai-message th {
      background-color: #f1f1f1;
    }

    .chat-footer {
      border-top: 1px solid #ddd;
      padding: 1rem;
      background-color: #f8f9fa;
    }

    /* The sliding table container */
    #studentsSection {
      position: fixed;
      top: 0;
      right: 0;
      width: 50%;
      height: 100%;
      background-color: #fff;
      border-left: 1px solid #ccc;
      transform: translateX(100%);
      transition: transform 0.5s ease;
      overflow-y: auto;
      padding: 1rem;
    }
    #studentsSection.show {
      transform: translateX(0);
    }

    .slideFromRight {
      animation: slideIn 0.5s forwards;
    }
    @keyframes slideIn {
      from { transform: translateX(100%); }
      to { transform: translateX(0); }
    }

    #serverStatus {
      position: fixed;
      bottom: 0; left: 0; right: 0;
      background-color: #343a40;
      color: #fff;
      text-align: center;
      padding: 0.5rem;
      font-size: 0.9rem;
    }

    @media (max-width: 576px) {
      .chat-container {
        margin: 1rem;
        height: 85vh;
      }
      .chat-bubble {
        max-width: 100%;
      }
      #studentsSection {
        width: 100%;
      }
    }
  </style>
</head>

<body>
  <div class="chat-container">
    <div class="chat-header">
      <h4 class="mb-0">Super Student Management Chat</h4>
    </div>
    <div class="chat-body" id="messages"></div>
    <div class="chat-footer">
      <div class="input-group">
        <input
          type="text"
          id="userInput"
          class="form-control"
          placeholder="Try 'Clean data', 'View students'..."
          onkeydown="handleKeyDown(event)"
        />
        <button class="btn btn-primary" onclick="sendPrompt()">Send</button>
      </div>
    </div>
  </div>

  <div id="studentsSection"></div>
  <div id="serverStatus">Server is LIVE</div>

  <script
    src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
  ></script>

  <script>
    const messagesContainer = document.getElementById('messages');
    const userInputField = document.getElementById('userInput');
    const studentsSection = document.getElementById('studentsSection');

    function addMessage(text, sender) {
      const bubble = document.createElement('div');
      bubble.classList.add('chat-bubble', sender === 'user' ? 'user-message' : 'ai-message');

      if (sender === 'ai' && (text.includes("<table") || text.includes("studentsSection"))) {
        bubble.innerHTML = text;
      } else {
        bubble.textContent = text;
      }
      messagesContainer.appendChild(bubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function handleKeyDown(event) {
      if (event.key === 'Enter') {
        sendPrompt();
      }
    }

    async function sendPrompt() {
      const userInput = userInputField.value.trim();
      if (!userInput) return;

      // Show user's message
      addMessage(userInput, 'user');

      const requestOptions = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: userInput })
      };

      try {
        const response = await fetch('/process_prompt', requestOptions);
        const data = await response.json();
        const reply = data.message || data.error || 'No response from AI.';
        processAIReply(reply);
      } catch (error) {
        console.error('Error:', error);
        addMessage('Error: Unable to connect to server.', 'ai');
      }

      userInputField.value = '';
    }

    function processAIReply(reply) {
      // If the reply includes <table or #studentsSection, show in side panel
      if (reply.includes("<table") || reply.includes("studentsSection")) {
        studentsSection.innerHTML = reply;
        studentsSection.classList.add('show');
      } else {
        addMessage(reply, 'ai');
      }
    }

    // Called by Save button in table
    function saveTableEdits() {
      studentsSection.classList.remove('show');
      addMessage("Table changes saved. Panel closed.", 'ai');
    }
  </script>
</body>
</html>
"""

@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    global conversation_memory, conversation_context
    data = request.json
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided."}), 400

    conversation_memory.append({"role": "user", "content": user_prompt})
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory = conversation_memory[-MAX_MEMORY:]

    # If user says "reset memory" or "cancel"
    if user_prompt.lower() in ["reset memory", "reset conversation", "cancel"]:
        conversation_memory.clear()
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    # The main state machine
    reply = handle_state_machine(user_prompt)

    conversation_memory.append({"role": "AI", "content": reply})
    save_memory_to_firestore()
    return jsonify({"message": reply}), 200

###############################################################################
# 17. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 18. Before First Request => Load Memory + Summaries
###############################################################################
@app.before_first_request
def load_on_startup():
    global conversation_memory, conversation_context, welcome_summary
    memory, ctx = load_memory_from_firestore()
    if memory:
        conversation_memory.extend(memory)
    if ctx:
        conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info(f"Startup summary: {summary}")

###############################################################################
# 19. Run Flask
###############################################################################
if __name__ == "__main__":
    # Load memory if any
    memory, ctx = load_memory_from_firestore()
    if memory:
        conversation_memory = memory
    if ctx:
        conversation_context = ctx

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()

    app.run(debug=True, port=8000)
