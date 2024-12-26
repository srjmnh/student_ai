import re
import os
import json
import random
import logging
import base64
from flask import Flask, request, jsonify, render_template

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
model = genai.GenerativeModel("models/gemini-1.5-flash")  
# If no access to Gemini, use "models/chat-bison-001" or similar

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
# 7. Utility to remove code fences
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
    If it fails, return None.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
    return None

def generate_student_id(name, age):
    random_number = random.randint(1000, 9999)
    name_part = (name[:4] if len(name) >= 4 else name).upper()
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def create_funny_prompt_for_new_student(name):
    """
    Gemini prompt to ask if user wants more details, in a witty tone.
    """
    return (
        f"Write a short witty statement acknowledging we have a new student '{name}'. "
        "Ask the user if they have any additional details they'd like to add, such as marks or attendance. "
        "Keep it under 40 words, with a slightly humorous twist."
    )

def create_comedic_confirmation(action, name=None, student_id=None):
    """
    Gemini-based comedic confirmation for add, update, delete.
    """
    if action == "add_student":
        prompt = (
            f"Generate a short, darkly funny success message confirming the addition of {name} (ID: {student_id})."
        )
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

def view_students_table():
    """
    Return a string containing an HTML table of all students.
    """
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    if not students:
        return "<p>No students found.</p>"

    # Build a minimal HTML table
    table_html = """<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
    <thead>
      <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Age</th>
        <th>Class</th>
        <th>Marks</th>
        <th>Attendance</th>
      </tr>
    </thead>
    <tbody>
    """
    for st in students:
        sid = st.get("id", "")
        sname = st.get("name", "")
        sage = st.get("age", "")
        sclass = st.get("class", "")
        smarks = st.get("grades", {})
        sattendance = st.get("attendance", "")

        # For readability, if smarks is a dict, show it
        if isinstance(smarks, dict):
            smarks_str = ', '.join([f"{k}:{v}" for k,v in smarks.items()])
        else:
            smarks_str = str(smarks)

        row = f"""
        <tr>
          <td>{sid}</td>
          <td>{sname}</td>
          <td>{sage}</td>
          <td>{sclass}</td>
          <td>{smarks_str}</td>
          <td>{sattendance}</td>
        </tr>
        """
        table_html += row

    table_html += "</tbody></table>"
    return table_html

def add_student(params):
    """
    Create or update a student doc with optional 'grades_history' for analytics.
    """
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
        # 'grades' could be a dict or partial
        grades = params.get("grades") or {}

        # Generate a new ID
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
            "grades": grades,  # e.g. { "Math": 88, "Science": 92 }
            "grades_history": []  # We can track changes over time
        }

        db.collection("students").document(student_id).set(student_data)
        logging.info(f"✅ Added student: {student_data}")
        log_activity("ADD_STUDENT", f"Added {name} (ID {student_id}).")

        confirmation = create_comedic_confirmation("add_student", name, student_id)
        return {"message": f"{confirmation} (ID: {student_id})"}, 200

    except Exception as e:
        logging.error(f"❌ Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    """
    We also store old grades in 'grades_history' to track changes over time.
    """
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
            if k not in ["id"]:
                update_fields[k] = v

        # If user is updating grades, let's store old in 'grades_history'
        if "grades" in update_fields:
            existing_data = doc_snapshot.to_dict()
            old_grades = existing_data.get("grades", {})
            # Create a new entry in grades_history
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
        logging.info(f"✅ Updated student {student_id} with {update_fields}")
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
        logging.info(f"✅ Deleted student ID {student_id}")
        log_activity("DELETE_STUDENT", f"Deleted student ID {student_id}")

        confirmation = create_comedic_confirmation("delete_student", student_id=student_id)
        return {"message": confirmation}, 200

    except Exception as e:
        logging.error(f"❌ Error in delete_student: {e}")
        return {"error": str(e)}, 500

def analytics_student(params):
    """
    Basic analytics: 
    - Compare old grades vs new to see if average is increasing
    - Return some witty analysis
    """
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing 'id' to analyze student."}, 400

        doc_snapshot = db.collection("students").document(student_id).get()
        if not doc_snapshot.exists:
            return {"error": f"No student with id {student_id} found."}, 404

        data = doc_snapshot.to_dict()
        grades_history = data.get("grades_history", [])
        # We can see if there's an upward trend in average
        # For simplicity: if there's 2 or more snapshots, compare avg of first vs avg of last
        if len(grades_history) < 1:
            return {"message": f"No historical grades found for {data['name']}"}, 200

        # We'll check the first vs last
        oldest = grades_history[0]["old_grades"]
        newest = grades_history[-1]["new_grades"]
        # If "old_grades" is empty in the first record, skip to next
        # We'll do a function to get average
        def avg_marks(grades):
            if not grades:
                return 0
            vals = [v for v in grades.values() if isinstance(v, (int, float))]
            if not vals:
                return 0
            return sum(vals) / len(vals)

        old_avg = avg_marks(oldest)
        new_avg = avg_marks(newest)
        trend = "improved" if new_avg > old_avg else "declined" if new_avg < old_avg else "stayed the same"

        message = f"{data['name']}'s performance has {trend}. Old avg={old_avg:.2f}, new avg={new_avg:.2f}."

        return {"message": message}, 200

    except Exception as e:
        logging.error(f"❌ Error in analytics_student: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 9. Classification + Enhanced
###############################################################################
def classify_user_input(user_prompt):
    """
    We'll allow synonyms like 'hire students' => view_students,
    'check performance' => analytics_student, etc.
    """
    classification_prompt = (
        "You are an advanced assistant that classifies user input into actions:\n"
        " - add_student\n"
        " - update_student\n"
        " - delete_student\n"
        " - view_students (including synonyms like 'hire students', 'list students', etc.)\n"
        " - analytics_student (like 'check performance of John')\n"
        "If the user input is not an action, return {\"type\": \"casual\"}.\n\n"
        "Return JSON only: {\"type\": \"firestore\", \"action\": \"...\", \"parameters\": {...}} or {\"type\": \"casual\"}.\n\n"
        f"User Input: '{user_prompt}'\n\n"
        "Output JSON only (no code fences)."
    )

    response = model.generate_content(classification_prompt)
    if not response.candidates:
        return {"type": "casual"}

    content = ''.join(part.text for part in response.candidates[0].content.parts).strip()
    content = remove_code_fences(content)

    try:
        data = json.loads(content)
        if "type" not in data:
            data["type"] = "casual"
        if data["type"] == "firestore":
            # Normalize synonyms
            synonyms_map = {
                "hire_students": "view_students",
                "hire": "view_students",
                "check_performance": "analytics_student",
                "performance": "analytics_student",
                "analytics": "analytics_student"
            }
            raw_action = data.get("action", "").lower().strip()
            if raw_action in synonyms_map:
                data["action"] = synonyms_map[raw_action]

        return data
    except (ValueError, json.JSONDecodeError):
        return {"type": "casual"}

###############################################################################
# 10. State Machine
###############################################################################
def handle_state_machine(user_prompt):
    state = conversation_context["state"]
    pending_params = conversation_context["pending_params"]
    last_action = conversation_context["last_intended_action"]

    if state == STATE_AWAITING_STUDENT_INFO:
        # Possibly parse new fields from user input
        # We'll define desired fields for a student
        desired_fields = ["name", "age", "class", "address", "phone", "guardian_name", "guardian_phone", "attendance", "grades"]
        extracted = extract_fields(user_prompt, desired_fields)
        for k, v in extracted.items():
            pending_params[k] = v

        # If we at least have a name, we can finalize the add
        if not pending_params.get("name"):
            return "I still need the student's name. Provide it or say 'cancel' to stop."

        result, status = add_student(pending_params)
        # Clear context
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None

        # Generate a follow-up from Gemini asking if they need more details
        if "message" in result and status == 200:
            # Additional comedic prompt
            funny_prompt = create_funny_prompt_for_new_student(pending_params["name"])
            followup_resp = model.generate_content(funny_prompt)
            if followup_resp.candidates:
                followup_text = followup_resp.candidates[0].content.parts[0].text.strip()
                return result["message"] + "\n\n" + followup_text
            else:
                return result["message"]
        else:
            return result.get("error", "Something went wrong adding student.")

    elif state == STATE_AWAITING_ANALYTICS_TARGET:
        # We might parse which student user is referring to
        # If they provide an ID, let's do analytics
        # Or if they provide a name, we can search for that student
        desired_fields = ["id", "name"]
        extracted = extract_fields(user_prompt, desired_fields)
        for k, v in extracted.items():
            pending_params[k] = v

        if pending_params.get("id"):
            # We have an ID
            result, status = analytics_student(pending_params)
            conversation_context["state"] = STATE_IDLE
            conversation_context["pending_params"] = {}
            conversation_context["last_intended_action"] = None
            return result.get("message", result.get("error", "Analytics error."))
        elif pending_params.get("name"):
            # Search for student by name
            # We'll do a simple equality search:
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
                # Multiple matches => ask which ID
                listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
                return f"Multiple students named {pending_params['name']} found:\n{listing}\nWhich ID do you want to analyze?"
        else:
            # We didn't get an id or name
            return "Which student do you want to check? Provide an ID or name."

    else:
        # state = IDLE => normal classification
        action_data = classify_user_input(user_prompt)
        if action_data.get("type") == "casual":
            # Just generate a casual response
            resp = model.generate_content(user_prompt)
            if resp.candidates:
                return resp.candidates[0].content.parts[0].text.strip()
            else:
                return "I'm at a loss for words..."

        elif action_data.get("type") == "firestore":
            action = action_data.get("action")
            params = action_data.get("parameters", {})

            # Check synonyms or direct
            if action == "view_students":
                # Return an HTML table of students
                table_html = view_students_table()
                return f"Here are the students in a nice table:\n{table_html}"

            elif action == "add_student":
                # If user has no name, we go to AWAITING_STUDENT_INFO
                if not params.get("name"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = params
                    conversation_context["last_intended_action"] = "add_student"
                    return "Let's add a new student. What's their name?"
                else:
                    # Add directly
                    result, status = add_student(params)
                    if status == 200 and "message" in result:
                        # Ask if they want more details
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
                # Must have an ID or at least something
                if not params.get("id"):
                    return "To update a student, please provide an 'id'."
                else:
                    result, status = update_student(params)
                    return result.get("message", result.get("error", "Update error."))

            elif action == "delete_student":
                # Must have an ID
                if not params.get("id"):
                    return "To delete a student, please provide an 'id'."
                else:
                    result, status = delete_student(params)
                    return result.get("message", result.get("error", "Delete error."))

            elif action == "analytics_student":
                # We'll move to state AWAITING_ANALYTICS_TARGET if user didn't supply an 'id' or 'name'
                if not (params.get("id") or params.get("name")):
                    conversation_context["state"] = STATE_AWAITING_ANALYTICS_TARGET
                    conversation_context["pending_params"] = params
                    conversation_context["last_intended_action"] = "analytics_student"
                    return "Which student do you want to check performance for? Provide an ID or name."
                else:
                    # We have something
                    return handle_analytics_call(params)

            else:
                return f"Unknown action: {action}"
        else:
            return "I couldn't classify your request. Please rephrase."

def handle_analytics_call(params):
    # If user gave an ID, do direct
    if params.get("id"):
        result, status = analytics_student(params)
        return result.get("message", result.get("error", "Analytics error."))
    elif params.get("name"):
        # same logic as in AWAITING_ANALYTICS_TARGET
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
# 11. Extraction of fields
###############################################################################
def extract_fields(user_input, desired_fields):
    prompt = (
        f"You are an assistant that extracts fields from user input. "
        f"Fields: {', '.join(desired_fields)}.\n"
        f"User Input: '{user_input}'\n\n"
        "Return JSON with only these fields if found.\n"
        "No extra text or code fences."
    )
    resp = model.generate_content(prompt)
    if resp.candidates:
        content = ''.join(part.text for part in resp.candidates[0].content.parts).strip()
        content = remove_code_fences(content)
        try:
            data = json.loads(content)
            return data
        except:
            return {}
    return {}

###############################################################################
# 12. Flask Routes
###############################################################################
@app.route("/")
def index():
    # Return a minimal HTML that hits /process_prompt
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Super Student Management</title>
</head>
<body>
    <h2>Welcome to the Super Student Management System</h2>
    <p>Open your chat UI or POST to <code>/process_prompt</code> with JSON { "prompt": "..." }</p>
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

    # Add to memory
    conversation_memory.append({"role": "user", "content": user_prompt})
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory = conversation_memory[-MAX_MEMORY:]

    # "reset memory" command
    if user_prompt.lower() in ["reset memory", "reset conversation"]:
        conversation_memory.clear()
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    # State machine
    reply = handle_state_machine(user_prompt)

    # Add AI reply
    conversation_memory.append({"role": "AI", "content": reply})
    save_memory_to_firestore()

    return jsonify({"message": reply}), 200

###############################################################################
# 13. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 14. Before First Request => Load Memory + Summaries
###############################################################################
@app.before_first_request
def load_on_startup():
    global conversation_memory, conversation_context, welcome_summary
    memory, ctx = load_memory_from_firestore()
    if memory:
        conversation_memory.extend(memory)
    if ctx:
        conversation_context.update(ctx)
    # Summaries
    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info(f"Startup summary: {summary}")

###############################################################################
# 15. Run Flask
###############################################################################
if __name__ == "__main__":
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
