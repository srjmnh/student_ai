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

# If you do NOT have access to Gemini, switch to "models/chat-bison-001":
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

def view_students_table():
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    if not students:
        return "<p>No students found.</p>"

    table_html = """<table style="width:100%; border:1px solid #ccc; border-collapse:collapse;">
    <thead>
      <tr>
        <th style="border:1px solid #ccc; padding:8px;">ID</th>
        <th style="border:1px solid #ccc; padding:8px;">Name</th>
        <th style="border:1px solid #ccc; padding:8px;">Age</th>
        <th style="border:1px solid #ccc; padding:8px;">Class</th>
        <th style="border:1px solid #ccc; padding:8px;">Marks</th>
        <th style="border:1px solid #ccc; padding:8px;">Attendance</th>
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

        if isinstance(smarks, dict):
            smarks_str = ', '.join([f"{k}:{v}" for k, v in smarks.items()])
        else:
            smarks_str = str(smarks)

        row = f"""
        <tr>
          <td style="border:1px solid #ccc; padding:8px;">{sid}</td>
          <td style="border:1px solid #ccc; padding:8px;">{sname}</td>
          <td style="border:1px solid #ccc; padding:8px;">{sage}</td>
          <td style="border:1px solid #ccc; padding:8px;">{sclass}</td>
          <td style="border:1px solid #ccc; padding:8px;">{smarks_str}</td>
          <td style="border:1px solid #ccc; padding:8px;">{sattendance}</td>
        </tr>
        """
        table_html += row

    table_html += "</tbody></table>"
    return table_html

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
            if k not in ["id"]:
                update_fields[k] = v

        # If user is updating 'grades', we store old in 'grades_history'
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
# 9. Classification
###############################################################################
def classify_user_input(user_prompt):
    classification_prompt = (
        "You are an advanced assistant that classifies user input into actions:\n"
        " - add_student\n"
        " - update_student\n"
        " - delete_student\n"
        " - view_students (including synonyms like 'hire students', 'list students', etc.)\n"
        " - analytics_student (like 'check performance')\n"
        "If not an action, return {\"type\": \"casual\"}.\n\n"
        "Output JSON only, e.g.:\n"
        "{ \"type\": \"firestore\", \"action\": \"add_student\", \"parameters\": {...} } or {\"type\": \"casual\"}.\n\n"
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
        # synonyms
        if data["type"] == "firestore":
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
    except:
        return {"type": "casual"}

###############################################################################
# 10. State Machine
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

def handle_state_machine(user_prompt):
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
            # see if multiple or single
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

    else:  # STATE_IDLE
        action_data = classify_user_input(user_prompt)
        if action_data.get("type") == "casual":
            resp = model.generate_content(user_prompt)
            if resp.candidates:
                return resp.candidates[0].content.parts[0].text.strip()
            else:
                return "I'm at a loss for words..."

        elif action_data.get("type") == "firestore":
            action = action_data.get("action", "")
            params = action_data.get("parameters", {})
            if action == "view_students":
                # Return an HTML table
                table_html = view_students_table()
                return f"Here are the students in a nice table:\n{table_html}"
            elif action == "add_student":
                if not params.get("name"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = params
                    conversation_context["last_intended_action"] = "add_student"
                    return "Let's add a new student. What's their name?"
                else:
                    # Add directly
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
                return f"Unknown action: {action}"
        else:
            return "I couldn't classify your request. Please rephrase."

###############################################################################
# 11. Flask Routes
###############################################################################
# This route returns the modern chat UI directly.
@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <!-- Ensures mobile responsiveness -->
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Super Student Management Chat</title>

  <!-- Bootstrap 5 CSS -->
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
      overflow: hidden; /* Hide any overflow beyond container */
    }

    .chat-header {
      background-color: #343a40; 
      color: #fff;
      padding: 1rem;
      text-align: center;
    }

    .chat-body {
      flex: 1; /* Expand to fill available vertical space */
      padding: 1rem;
      overflow-y: auto; /* Make chat scrollable */
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

    @media (max-width: 576px) {
      .chat-container {
        margin: 1rem;
        height: 85vh;
      }
      .chat-bubble {
        max-width: 100%;
      }
    }
  </style>
</head>

<body>
  <div class="chat-container">
    <div class="chat-header">
      <h4 class="mb-0">Super Student Management Chat</h4>
    </div>

    <div class="chat-body d-flex flex-column" id="messages">
      <!-- Chat messages will appear here dynamically -->
    </div>

    <div class="chat-footer">
      <div class="input-group">
        <input
          type="text"
          id="userInput"
          class="form-control"
          placeholder="E.g. 'Add a new student', 'Hire students', 'Check performance of John'..."
          onkeydown="handleKeyDown(event)"
        />
        <button class="btn btn-primary" onclick="sendPrompt()">Send</button>
      </div>
    </div>
  </div>

  <script
    src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
  ></script>

  <script>
    const messagesContainer = document.getElementById('messages');
    const userInputField = document.getElementById('userInput');

    function addMessage(text, sender) {
      const bubble = document.createElement('div');
      bubble.classList.add('chat-bubble', sender === 'user' ? 'user-message' : 'ai-message');

      // If AI message might contain HTML (e.g. a table), render with innerHTML
      if (sender === 'ai') {
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

      addMessage(userInput, 'user');

      const requestOptions = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: userInput }),
      };

      try {
        const response = await fetch('/process_prompt', requestOptions);
        const data = await response.json();
        const reply = data.message || data.error || 'No response from AI.';
        addMessage(reply, 'ai');
      } catch (error) {
        console.error('Error:', error);
        addMessage('Error: Unable to connect to server.', 'ai');
      }

      userInputField.value = '';
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

    if user_prompt.lower() in ["reset memory", "reset conversation", "cancel"]:
        conversation_memory.clear()
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    reply = handle_state_machine(user_prompt)

    conversation_memory.append({"role": "AI", "content": reply})
    save_memory_to_firestore()
    return jsonify({"message": reply}), 200

###############################################################################
# 12. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 13. Before First Request => Load Memory + Summaries
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
# 14. Run Flask
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
