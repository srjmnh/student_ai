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
        logging.info(f"✅ Logged activity: {action_type}, details={details}")
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
# 7. Utility: remove code fences + safe int
###############################################################################
def remove_code_fences(text: str) -> str:
    fenced_pattern = r'^```(?:json)?\s*([\s\S]*?)\s*```$'
    match = re.match(fenced_pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text

def _safe_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

###############################################################################
# 8. Bulk Update for Table Editing
###############################################################################
def bulk_update_students(student_list):
    updated_ids = []
    for st in student_list:
        sid = st.get("id")
        if not sid:
            continue
        doc_ref = db.collection("students").document(sid)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            logging.warning(f"Document not found for ID {sid}")
            continue

        fields_to_update = {}
        for k, v in st.items():
            if k == "id":
                continue
            if k == "age":
                fields_to_update["age"] = _safe_int(v)
            else:
                fields_to_update[k] = v
        doc_ref.update(fields_to_update)
        updated_ids.append(sid)

    if updated_ids:
        log_activity("BULK_UPDATE", f"Updated IDs: {updated_ids}")
    return updated_ids

###############################################################################
# 9. Improved Cleanup Data (Deduplicate)
###############################################################################
def cleanup_data():
    """
    Finds duplicates by 'name', keeps the doc with the highest field count, 
    deletes the rest. Handles missing 'id' or non-string 'name' gracefully.
    """
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    from collections import defaultdict
    name_groups = defaultdict(list)

    for st in students:
        # Convert name to string to avoid .strip() on None
        raw_name = str(st.get("name") or "")
        st_name = raw_name.strip().lower()
        if st_name:
            name_groups[st_name].append(st)

    duplicates_deleted = []
    for name_val, group in name_groups.items():
        if len(group) > 1:
            best_student = None
            best_score = -1

            for st in group:
                # Defensive check: ensure 'id' is present
                doc_id = st.get("id")
                if not doc_id:
                    logging.warning(f"Skipping doc with missing 'id': {st}")
                    continue
                # Count how many non-empty fields
                score = sum(1 for v in st.values() if v not in [None, "", {}])
                if score > best_score:
                    best_score = score
                    best_student = st

            if not best_student:
                logging.warning(f"No valid 'best_student' found in group {group}")
                continue

            best_id = best_student.get("id")
            if not best_id:
                logging.warning(f"Best student is missing 'id': {best_student}")
                continue

            # Delete others
            for st in group:
                doc_id = st.get("id")
                if doc_id and doc_id != best_id:
                    try:
                        db.collection("students").document(doc_id).delete()
                        duplicates_deleted.append(doc_id)
                    except Exception as e:
                        logging.error(f"Error deleting doc {doc_id}: {e}")

    if duplicates_deleted:
        log_activity("CLEANUP_DATA", f"Deleted duplicates: {duplicates_deleted}")

    return build_students_table_html("Data cleaned! Updated student records below:")

###############################################################################
# 10. Building an Editable Table that Slides
###############################################################################
def build_students_table_html(heading="Student Records"):
    docs = db.collection("students").stream()
    students = [doc.to_dict() for doc in docs]

    if not students:
        return "<p>No students found.</p>"

    table_html = f"""
<div id="studentsSection" class="slideFromRight">
  <h4>{heading}</h4>
  <table class="table table-bordered table-sm">
    <thead class="table-light">
      <tr>
        <th>ID</th>
        <th contenteditable="false">Name</th>
        <th contenteditable="false">Age</th>
        <th contenteditable="false">Class</th>
        <th contenteditable="false">Address</th>
        <th contenteditable="false">Phone</th>
        <th contenteditable="false">Guardian</th>
        <th contenteditable="false">Guardian Phone</th>
        <th contenteditable="false">Attendance</th>
        <th contenteditable="false">Grades</th>
      </tr>
    </thead>
    <tbody>
    """
    for st in students:
        sid = st.get("id","")
        name = st.get("name","")
        age = st.get("age","")
        sclass = st.get("class","")
        address = st.get("address","")
        phone = st.get("phone","")
        guardian_name = st.get("guardian_name","")
        guardian_phone = st.get("guardian_phone","")
        attendance = st.get("attendance","")
        grades = st.get("grades","")

        # Convert dict grades to JSON
        if isinstance(grades, dict):
            grades = json.dumps(grades)

        row_html = f"""
        <tr data-id="{sid}">
          <td style="color:#555; user-select:none;">{sid}</td>
          <td contenteditable="true">{name}</td>
          <td contenteditable="true">{age}</td>
          <td contenteditable="true">{sclass}</td>
          <td contenteditable="true">{address}</td>
          <td contenteditable="true">{phone}</td>
          <td contenteditable="true">{guardian_name}</td>
          <td contenteditable="true">{guardian_phone}</td>
          <td contenteditable="true">{attendance}</td>
          <td contenteditable="true">{grades}</td>
        </tr>
        """
        table_html += row_html
    table_html += """
    </tbody>
  </table>
  <button class="btn btn-success" onclick="saveTableEdits()">Save</button>
</div>
"""
    return table_html

###############################################################################
# 11. Student Logic (Add, Update, Delete, Analytics) 
###############################################################################
def generate_student_id(name, age):
    random_number = random.randint(1000, 9999)
    name_part = (name[:4].upper() if len(name)>=4 else name.upper())
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def create_funny_prompt_for_new_student(name):
    return (
        f"Write a short witty statement acknowledging we have a new student '{name}'. "
        "Ask if they'd like to add details like marks or attendance. Under 40 words, humorous."
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

        sid = generate_student_id(name, age)
        student_doc = {
            "id": sid,
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
        db.collection("students").document(sid).set(student_doc)
        log_activity("ADD_STUDENT", f"Added {name} (ID {sid}).")

        confirm_msg = create_comedic_confirmation("add_student", name, sid)
        return {"message": f"{confirm_msg} (ID: {sid})"}, 200
    except Exception as e:
        logging.error(f"Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    try:
        sid = params.get("id")
        if not sid:
            return {"error": "Missing student 'id'."}, 400

        doc_ref = db.collection("students").document(sid)
        snap = doc_ref.get()
        if not snap.exists:
            return {"error": f"No doc with id {sid} found."}, 404

        update_fields = {}
        for k, v in params.items():
            if k == "id":
                continue
            if k == "grades":
                old_grades = snap.to_dict().get("grades", {})
                new_entry = {
                    "old_grades": old_grades,
                    "new_grades": v,
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
                hist = snap.to_dict().get("grades_history", [])
                hist.append(new_entry)
                update_fields["grades_history"] = hist
            update_fields[k] = v

        doc_ref.update(update_fields)
        log_activity("UPDATE_STUDENT", f"Updated {sid} with {update_fields}")

        cmsg = create_comedic_confirmation("update_student", student_id=sid)
        return {"message": cmsg}, 200
    except Exception as e:
        logging.error(f"update_student error: {e}")
        return {"error": str(e)}, 500

def delete_student(params):
    try:
        sid = params.get("id")
        if not sid:
            return {"error": "Missing 'id' to delete."}, 400
        doc_ref = db.collection("students").document(sid)
        if not doc_ref.get().exists:
            return {"error": f"No doc with id {sid} found."}, 404

        doc_ref.delete()
        log_activity("DELETE_STUDENT", f"Deleted {sid}")

        cmsg = create_comedic_confirmation("delete_student", student_id=sid)
        return {"message": cmsg}, 200
    except Exception as e:
        logging.error(f"delete_student error: {e}")
        return {"error": str(e)}, 500

def analytics_student(params):
    try:
        sid = params.get("id")
        if not sid:
            return {"error": "Missing 'id' for analytics."}, 400

        snap = db.collection("students").document(sid).get()
        if not snap.exists:
            return {"error": f"No doc with id {sid}."}, 404

        data = snap.to_dict()
        hist = data.get("grades_history", [])
        if not hist:
            return {"message": f"No historical grades for {data['name']}."}, 200

        def avg_marks(grds):
            if not isinstance(grds, dict):
                return 0
            vals = [val for val in grds.values() if isinstance(val, (int, float))]
            return sum(vals) / len(vals) if vals else 0

        oldest = hist[0]["old_grades"]
        newest = hist[-1]["new_grades"]
        old_avg = avg_marks(oldest)
        new_avg = avg_marks(newest)
        trend = "improved" if new_avg > old_avg else "declined" if new_avg < old_avg else "stayed the same"

        msg = f"{data['name']}'s performance has {trend}. old={old_avg}, new={new_avg}"
        return {"message": msg}, 200
    except Exception as e:
        logging.error(f"analytics_student error: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 12. Classification for "Casual" vs "Firestore"
###############################################################################
def classify_casual_or_firestore(user_prompt):
    classification_prompt = (
        "You are an advanced assistant that decides if the user prompt is casual conversation or a Firestore operation.\n"
        "If casual => {\"type\":\"casual\"}\n"
        "If firestore => {\"type\":\"firestore\",\"action\":\"...\",\"parameters\":{...}}\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student.\n"
        f"User Prompt:'{user_prompt}'\n"
        "Output JSON only."
    )
    resp = model.generate_content(classification_prompt)
    if not resp.candidates:
        return {"type": "casual"}
    raw = resp.candidates[0].content.parts[0].text.strip()
    raw = remove_code_fences(raw)
    try:
        data = json.loads(raw)
        if "type" not in data:
            data["type"] = "casual"
        return data
    except:
        return {"type": "casual"}

###############################################################################
# 13. Additional Field Extraction
###############################################################################
def extract_fields(user_input, desired_fields):
    prompt = (
        f"You are an assistant that extracts fields from user input.\n"
        f"Fields: {', '.join(desired_fields)}\n"
        f"User Input:'{user_input}'\n"
        "Return JSON with only those fields.\n"
    )
    resp = model.generate_content(prompt)
    if not resp.candidates:
        return {}
    raw = ''.join(part.text for part in resp.candidates[0].content.parts).strip()
    raw = remove_code_fences(raw)
    try:
        return json.loads(raw)
    except:
        return {}

###############################################################################
# 14. Analytics Helper
###############################################################################
def handle_analytics_call(params):
    if params.get("id"):
        out, stat = analytics_student(params)
        return out.get("message", out.get("error", "Analytics error."))
    elif params.get("name"):
        docs = db.collection("students").where("name", "==", params["name"]).stream()
        matches = [d.to_dict() for d in docs]
        if not matches:
            return f"No student named {params['name']}."
        if len(matches) == 1:
            params["id"] = matches[0]["id"]
            out, stat = analytics_student(params)
            return out.get("message", out.get("error", "Error."))
        else:
            listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
            return f"Multiple found:\n{listing}\nWhich ID?"
    else:
        return "Which student to analyze? Provide ID or name."

###############################################################################
# 15. The Main State Machine
###############################################################################
def handle_state_machine(user_prompt):
    state = conversation_context["state"]
    pend = conversation_context["pending_params"]

    # If partial add
    if state == STATE_AWAITING_STUDENT_INFO:
        desired = ["name","age","class","address","phone","guardian_name","guardian_phone","attendance","grades"]
        found = extract_fields(user_prompt, desired)
        for k,v in found.items():
            pend[k] = v
        if not pend.get("name"):
            return "I still need name. Provide or 'cancel'."

        out, st = add_student(pend)
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None

        if st == 200 and "message" in out:
            # comedic follow-up
            funny_prompt = create_funny_prompt_for_new_student(pend["name"])
            r2 = model.generate_content(funny_prompt)
            if r2.candidates:
                txt = r2.candidates[0].content.parts[0].text.strip()
                return out["message"] + "\n\n" + txt
            else:
                return out["message"]
        else:
            return out.get("error", "Error adding student.")

    # If partial analytics
    elif state == STATE_AWAITING_ANALYTICS_TARGET:
        desired = ["id","name"]
        found = extract_fields(user_prompt, desired)
        for k,v in found.items():
            pend[k] = v
        if pend.get("id"):
            out, st = analytics_student(pend)
            conversation_context["state"] = STATE_IDLE
            conversation_context["pending_params"] = {}
            conversation_context["last_intended_action"] = None
            return out.get("message", out.get("error", "Error."))
        elif pend.get("name"):
            docs = db.collection("students").where("name","==", pend["name"]).stream()
            matches = [doc.to_dict() for doc in docs]
            if not matches:
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return f"No student named {pend['name']}."
            if len(matches) == 1:
                pend["id"] = matches[0]["id"]
                out, st = analytics_student(pend)
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return out.get("message", out.get("error", "Error."))
            else:
                lst = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
                return f"Multiple found:\n{lst}\nWhich ID?"
        else:
            return "Which student? ID or name."

    # Otherwise, we are IDLE => classify
    else:
        c = classify_casual_or_firestore(user_prompt)
        if c.get("type") == "casual":
            # casual
            r = model.generate_content(user_prompt)
            if r.candidates:
                return r.candidates[0].content.parts[0].text.strip()
            else:
                return "I have nothing to say."
        elif c.get("type") == "firestore":
            a = c.get("action","")
            p = c.get("parameters",{})
            if a == "view_students":
                return build_students_table_html("Student Records")
            elif a == "cleanup_data":
                return cleanup_data()
            elif a == "add_student":
                if not p.get("name"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = p
                    conversation_context["last_intended_action"] = "add_student"
                    return "Let's add new student. What's their name?"
                else:
                    out, st = add_student(p)
                    if st == 200 and "message" in out:
                        # comedic
                        funny= create_funny_prompt_for_new_student(p["name"])
                        r2= model.generate_content(funny)
                        if r2.candidates:
                            txt= r2.candidates[0].content.parts[0].text.strip()
                            return out["message"]+"\n\n"+txt
                        else:
                            return out["message"]
                    else:
                        return out.get("error","Error adding student.")
            elif a == "update_student":
                if not p.get("id"):
                    return "To update, need 'id'."
                out, st = update_student(p)
                return out.get("message", out.get("error","Error."))
            elif a == "delete_student":
                if not p.get("id"):
                    return "Need 'id' to delete."
                out,st= delete_student(p)
                return out.get("message", out.get("error","Error."))
            elif a == "analytics_student":
                if not (p.get("id") or p.get("name")):
                    conversation_context["state"]= STATE_AWAITING_ANALYTICS_TARGET
                    conversation_context["pending_params"]= p
                    conversation_context["last_intended_action"]="analytics_student"
                    return "Which student to check? Provide ID or name."
                else:
                    return handle_analytics_call(p)
            else:
                return f"Unknown Firestore action: {a}"
        else:
            return "I'm not sure. Is it casual or a Firestore request?"

###############################################################################
# 16. Flask + HTML
###############################################################################
@app.route("/")
def index():
    """
    Return the chat UI (left) + sliding table panel (right).
    Edits are saved via /bulk_update_students
    """
    return """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Super Student Management</title>
  <link rel="stylesheet" 
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
  <style>
    body { margin:0; padding:0; background:#f8f9fa; }
    .chat-wrap {
      max-width:700px; margin:2rem auto; background:#fff; 
      border-radius:0.5rem; box-shadow:0 4px 10px rgba(0,0,0,0.1);
      display:flex; flex-direction:column; height:80vh; overflow:hidden;
      transition: transform 0.5s ease;
    }
    .chat-header { background:#343a40; color:#fff; padding:1rem; text-align:center; }
    .chat-body { flex:1; padding:1rem; overflow-y:auto; display:flex; flex-direction:column; }
    .chat-bubble {
      margin-bottom:0.75rem; padding:0.75rem 1rem; border-radius:15px; 
      max-width:75%; word-wrap:break-word; white-space:pre-wrap;
    }
    .user-msg { background:#007bff; color:#fff; align-self:flex-end; border-bottom-right-radius:0; }
    .ai-msg   { background:#e9ecef; color:#000; align-self:flex-start; border-bottom-left-radius:0; }
    .chat-footer { border-top:1px solid #ddd; padding:1rem; background:#f8f9fa; }
    #tablePanel {
      position:fixed; top:0; right:0; width:50%; height:100%; 
      background:#fff; border-left:1px solid #ccc; padding:1rem; 
      overflow-y:auto; transform:translateX(100%); transition:transform 0.5s ease;
    }
    #tablePanel.show { transform:translateX(0%); }
    #chatSection.slideLeft { transform:translateX(-20%); }

    /* contenteditable formatting */
    td[contenteditable="true"] {
      outline:1px dashed #ccc; 
    }
  </style>
</head>
<body>
  <div class="chat-wrap" id="chatSection">
    <div class="chat-header">
      <h4>Student Management Chat</h4>
    </div>
    <div class="chat-body" id="chatBody"></div>
    <div class="chat-footer">
      <div class="input-group">
        <input type="text" class="form-control" id="userInput" placeholder="Ask me something..."
               onkeydown="if(event.key==='Enter') sendPrompt();">
        <button class="btn btn-primary" onclick="sendPrompt()">Send</button>
      </div>
    </div>
  </div>

  <div id="tablePanel"></div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

  <script>
    const chatBody = document.getElementById('chatBody');
    const userInput = document.getElementById('userInput');
    const chatSection= document.getElementById('chatSection');
    const tablePanel= document.getElementById('tablePanel');

    function addBubble(text, isUser=false) {
      const bubble= document.createElement('div');
      bubble.classList.add('chat-bubble', isUser ? 'user-msg' : 'ai-msg');
      bubble.innerHTML = text;
      chatBody.appendChild(bubble);
      chatBody.scrollTop= chatBody.scrollHeight;
    }

    async function sendPrompt() {
      const prompt= userInput.value.trim();
      if(!prompt) return;
      addBubble(prompt,true);
      userInput.value='';

      try {
        const resp= await fetch('/process_prompt',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ prompt })
        });
        const data= await resp.json();
        const reply= data.message || data.error || 'No response.';
        parseReply(reply);
      } catch(err) {
        addBubble("Error connecting to server: "+err,false);
      }
    }

    function parseReply(reply) {
      // If reply includes <table or 'slideFromRight', we show in tablePanel
      if(reply.includes('<table') || reply.includes('slideFromRight')) {
        tablePanel.innerHTML= reply;
        tablePanel.classList.add('show');
        chatSection.classList.add('slideLeft');
      } else {
        addBubble(reply,false);
      }
    }

    // Called by "Save" button in the table
    async function saveTableEdits() {
      // gather each row
      const rows= tablePanel.querySelectorAll('table tbody tr');
      const updates= [];
      rows.forEach( r => {
        const cells= r.querySelectorAll('td');
        if(!cells.length) return;
        // id is in cell[0]
        const sid= cells[0].innerText.trim();
        if(!sid) return;
        // name=1, age=2, class=3, address=4, phone=5, guardian=6, guardianPhone=7, attendance=8, grades=9
        let name= cells[1].innerText.trim();
        let age= cells[2].innerText.trim();
        let sclass= cells[3].innerText.trim();
        let address= cells[4].innerText.trim();
        let phone= cells[5].innerText.trim();
        let guardian= cells[6].innerText.trim();
        let guardianPhone= cells[7].innerText.trim();
        let attendance= cells[8].innerText.trim();
        let grades= cells[9].innerText.trim();
        // If grades is JSON
        try {
          grades= JSON.parse(grades);
        } catch(e) {
          // fallback
        }
        updates.push({
          id:sid,
          name,
          age,
          class:sclass,
          address,
          phone,
          guardian_name: guardian,
          guardian_phone: guardianPhone,
          attendance,
          grades
        });
      });

      try {
        const res= await fetch('/bulk_update_students',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ updates })
        });
        const data= await res.json();
        if(data.success) {
          addBubble("Changes saved to Firebase!",false);
        } else {
          addBubble("Error saving changes: "+(data.error||'unknown'), false);
        }
      } catch(err) {
        addBubble("Error saving changes: "+err, false);
      }
      // close panel
      tablePanel.classList.remove('show');
      chatSection.classList.remove('slideLeft');
    }
  </script>
</body>
</html>
"""

###############################################################################
# 17. "bulk_update_students" Route
###############################################################################
@app.route("/bulk_update_students", methods=["POST"])
def bulk_update_students_route():
    data = request.json
    updates = data.get("updates", [])
    if not updates:
        return jsonify({"error": "No updates provided."}), 400

    updated_ids = bulk_update_students(updates)
    return jsonify({"success": True, "updated_ids": updated_ids}), 200

###############################################################################
# 18. The main conversation route
###############################################################################
@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    global conversation_memory, conversation_context
    data = request.json
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided."}), 400

    conversation_memory.append({"role": "user", "content": user_prompt})
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory[:] = conversation_memory[-MAX_MEMORY:]

    if user_prompt.lower() in ["reset memory", "reset conversation", "cancel"]:
        conversation_memory.clear()
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    # handle
    reply = handle_state_machine(user_prompt)
    conversation_memory.append({"role": "AI", "content": reply})
    save_memory_to_firestore()
    return jsonify({"message": reply}), 200

###############################################################################
# 19. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exc(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 20. On Startup => Load Memory
###############################################################################
@app.before_first_request
def load_on_start():
    global conversation_memory, conversation_context, welcome_summary
    mem, ctx = load_memory_from_firestore()
    if mem:
        conversation_memory.extend(mem)
    if ctx:
        conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info("Startup summary: " + summary)

###############################################################################
# 21. Run
###############################################################################
if __name__ == "__main__":
    mem, ctx = load_memory_from_firestore()
    conversation_memory.extend(mem)
    conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()

    app.run(debug=True, port=8000)
