import re
import os
import json
import random
import logging
import base64
from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

###############################################################################
# 1. Flask Setup
###############################################################################
app = Flask(__name__)

###############################################################################
# 2. Configure Logging
###############################################################################
# Determine Environment
ENV = os.getenv("FLASK_ENV", "production")  # Default to production

# Configure Logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

if ENV == "development":
    # File Handler for Development
    # Ensure 'logs' directory exists
    if not os.path.exists("logs"):
        os.makedirs("logs")
    file_handler = logging.FileHandler("logs/app.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

# Console Handler for All Environments
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

###############################################################################
# 3. Configure Gemini (Google Generative AI)
###############################################################################
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

genai.configure(api_key=GEMINI_API_KEY)
# If you do NOT have access to gemini-1.5-flash, switch to "models/chat-bison-001"
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
# 5. Conversation + States
###############################################################################
conversation_memory = []
MAX_MEMORY = 20
welcome_summary = ""

# States
STATE_IDLE = "IDLE"
STATE_AWAITING_STUDENT_INFO = "AWAITING_STUDENT_INFO"
STATE_AWAITING_ANALYTICS_TARGET = "AWAITING_ANALYTICS_TARGET"
STATE_AWAITING_DELETE_CHOICE = "STATE_AWAITING_DELETE_CHOICE"
STATE_AWAITING_VIEW_FILTER = "AWAITING_VIEW_FILTER"  # New State for Filtering

conversation_context = {
    "state": STATE_IDLE,
    "pending_params": {},
    "last_intended_action": None,
    "delete_candidates": []
}

def save_memory_to_firestore():
    try:
        db.collection('conversation_memory').document('session_1').set({
            "memory": conversation_memory,
            "context": conversation_context
        })
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
# 6. Summaries
###############################################################################
def generate_comedic_summary_of_past_activities():
    """
    Grabs last 100 logs from 'activity_log' and asks Gemini to produce
    a short dark/funny summary.
    """
    try:
        logs = db.collection('activity_log').order_by('timestamp').limit(100).stream()
        lines = []
        for l in logs:
            d = l.to_dict()
            lines.append(f"{d.get('action_type')}: {d.get('details')}")
        if not lines:
            return "Strangely quiet. No records... yet."

        prompt = (
            "As a grimly funny AI, summarize these student management logs under 50 words:\n\n"
            + "\n".join(lines)
        )
        resp = model.generate_content(prompt)
        if resp.candidates:
            return resp.candidates[0].content.parts[0].text.strip()
        else:
            return "No comedic summary. The silence is deafening."
    except Exception as e:
        logging.error(f"❌ generate_comedic_summary_of_past_activities error: {e}")
        return "An error occurred rummaging through the logs."

###############################################################################
# 7. Utils
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
# 8. Firestore Logic
###############################################################################
def delete_student_doc(doc_id):
    """
    Directly delete doc from Firestore by ID.
    Returns (ok, message).
    """
    ref = db.collection("students").document(doc_id)
    snap = ref.get()
    if not snap.exists():
        return False, "No doc with that ID."
    ref.delete()
    return True, "deleted"

###############################################################################
# 9. Student Functions
###############################################################################
def gen_student_id(name, age, division):
    r = random.randint(1000, 9999)
    part = (name[:4].upper() if len(name) >= 4 else name.upper())
    a = str(age) if age else "00"
    d = division.upper()
    return f"{part}{a}{d}{r}"

def comedic_confirmation(action, name=None, doc_id=None):
    if action == "add_student":
        pr = f"Generate a short, darkly funny success confirming new student {name} ID {doc_id}."
    elif action == "delete_student":
        pr = f"Create a short, darkly witty message confirming the deletion of ID {doc_id}."
    elif action == "add_grade":
        pr = f"Generate a humorous confirmation for adding a new grade for subject {name} with ID {doc_id}."
    elif action == "delete_grade":
        pr = f"Create a short, darkly witty message confirming the deletion of grade for ID {doc_id}."
    elif action == "update_grade":
        pr = f"Generate a humorous confirmation for updating grades for subject ID {doc_id}."
    else:
        pr = "A cryptic success message."
    resp = model.generate_content(pr)
    if resp.candidates:
        return resp.candidates[0].content.parts[0].text.strip()[:100]
    else:
        return "Action done."

def add_student(params):
    name = params.get("name")
    if not name:
        return {"error": "Missing 'name'."}, 400
    age = _safe_int(params.get("age"))
    sclass = params.get("class")
    division = params.get("division")
    if not sclass or not division:
        return {"error": "Missing 'class' or 'division'."}, 400
    sid = gen_student_id(name, age, division)
    doc = {
        "id": sid,
        "name": name,
        "age": age,
        "class": sclass,
        "division": division,  # Added division
        "address": params.get("address"),
        "phone": params.get("phone"),
        "guardian_name": params.get("guardian_name"),
        "guardian_phone": params.get("guardian_phone"),
        "attendance": params.get("attendance"),
        "grades": params.get("grades") or {},
        "grades_history": []
    }
    db.collection("students").document(sid).set(doc)
    log_activity("ADD_STUDENT", f"Added {name} => {sid}")
    conf = comedic_confirmation("add_student", name, sid)
    return {"message": f"{conf} (ID: {sid})"}, 200

def update_student(params):
    sid = params.get("id")
    if not sid:
        return {"error": "Missing 'id'."}, 400
    ref = db.collection("students").document(sid)
    snap = ref.get()
    if not snap.exists():
        return {"error": f"No doc {sid} found."}, 404
    upd = {}
    for k, v in params.items():
        if k == "id":
            continue
        if k == "grades":
            old_g = snap.to_dict().get("grades", {})
            h = snap.to_dict().get("grades_history", [])
            h.append({"old": old_g, "new": v})
            upd["grades_history"] = h
        upd[k] = v
    # Validation: Ensure 'class' and 'division' are not empty if they are being updated
    if 'class' in upd and not upd['class']:
        return {"error": "The 'class' field cannot be empty."}, 400
    if 'division' in upd and not upd['division']:
        return {"error": "The 'division' field cannot be empty."}, 400
    ref.update(upd)
    log_activity("UPDATE_STUDENT", f"Updated {sid} => {upd}")
    c = comedic_confirmation("update_student", doc_id=sid)
    return {"message": c}, 200

def analytics_student(params):
    sid = params.get("id")
    if not sid:
        return {"error": "Missing 'id'."}, 400
    ref = db.collection("students").document(sid)
    snap = ref.get()
    if not snap.exists():
        return {"error": f"No doc with id {sid}."}, 404
    # Minimal stub or implement analytics logic here
    return {"message": "(Analytics not fully implemented)."}, 200

###############################################################################
# 10. Classification
###############################################################################
def classify_casual_or_firestore(prompt):
    cp = (
        "You are an advanced assistant that decides if the user prompt is casual or a Firestore operation.\n"
        "If casual => {\"type\":\"casual\"}\n"
        "If firestore => {\"type\":\"firestore\",\"action\":\"...\",\"parameters\":{...}}\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student, view_grades, add_grade, update_grade, delete_grade.\n"
        f"User Prompt:'{prompt}'\n"
        "Output JSON only."
    )
    r = model.generate_content(cp)
    if not r.candidates:
        return {"type": "casual"}
    raw = r.candidates[0].content.parts[0].text.strip()
    raw = remove_code_fences(raw)
    try:
        d = json.loads(raw)
        if "type" not in d:
            d["type"] = "casual"
        return d
    except:
        return {"type": "casual"}

###############################################################################
# 11. Searching & Deletion
###############################################################################
def search_students_by_name(name):
    docs = db.collection("students").where("name", "==", name).stream()
    results = []
    for d in docs:
        st = d.to_dict()
        st["id"] = d.id
        results.append(st)
    return results

def interpret_delete_choice(user_input, candidates):
    txt = user_input.strip().lower()
    if txt in ["first", "1", "one"]:
        if len(candidates) > 0:
            return candidates[0]["id"]
    elif txt in ["second", "2", "two"]:
        if len(candidates) > 1:
            return candidates[1]["id"]
    for c in candidates:
        if txt == c["id"].lower():
            return c["id"]
    return None

###############################################################################
# 12. Cleanup_data + build_students_table_html
###############################################################################
def cleanup_data():
    """
    Reads docs from Firestore, removes duplicates by name (keeps the most complete record),
    and removes documents with no name.
    """
    all_docs = db.collection("students").stream()
    doc_map = {}
    records = []
    for d in all_docs:
        data = d.to_dict()
        data["id"] = d.id  # real doc ID
        doc_map[d.id] = d  # store reference if needed
        records.append(data)

    from collections import defaultdict
    name_groups = defaultdict(list)
    removed_for_no_name = []
    for st in records:
        nm = str(st.get("name") or "").strip().lower()
        if not nm:
            # remove doc
            ref = doc_map[st["id"]]
            ref.reference.delete()
            removed_for_no_name.append(st["id"])
            continue
        name_groups[nm].append(st)

    duplicates_removed = []
    for nm, group in name_groups.items():
        if len(group) > 1:
            # find best doc
            best_score = -1
            best_student = None
            for st in group:
                score = sum(1 for v in st.values() if v not in [None, "", {}])
                if score > best_score:
                    best_score = score
                    best_student = st
            best_id = best_student["id"]
            for st in group:
                if st["id"] != best_id:
                    doc_map[st["id"]].reference.delete()
                    duplicates_removed.append(st["id"])

    if removed_for_no_name:
        log_activity("CLEANUP_DATA", f"Removed doc(s) missing name => {removed_for_no_name}")
    if duplicates_removed:
        log_activity("CLEANUP_DATA", f"Removed duplicates => {duplicates_removed}")

    return build_students_table_html("Data cleaned! Updated student records below:")

def build_students_table_html(heading="Student Records", sclass=None, division=None):
    # New: Allow filtering by class and division
    # Fetch class and division if provided
    from flask import request  # Import here to avoid circular imports

    query = db.collection("students")
    if sclass and division:
        query = query.where("class", "==", sclass).where("division", "==", division)
    elif sclass:
        query = query.where("class", "==", sclass)
    elif division:
        query = query.where("division", "==", division)

    all_docs = query.stream()
    docs_list = []
    for d in all_docs:
        st = d.to_dict()
        st["id"] = d.id
        docs_list.append(st)

    if not docs_list:
        return "<p>No students found for the specified filters.</p>"

    html = f"""
<div id="studentsSection" class="slideFromRight">
  <h4>{heading}</h4>
  <table class="table table-bordered table-sm">
    <thead class="table-light">
      <tr>
        <th>ID</th>
        <th contenteditable="false">Name</th>
        <th contenteditable="false">Age</th>
        <th contenteditable="false">Class</th>
        <th contenteditable="false">Division</th> <!-- Added Division -->
        <th contenteditable="false">Address</th>
        <th contenteditable="false">Phone</th>
        <th contenteditable="false">Guardian</th>
        <th contenteditable="false">Guardian Phone</th>
        <th contenteditable="false">Attendance</th>
        <th contenteditable="false">Grades</th>
        <th contenteditable="false">Action</th> <!-- Added Action Column -->
      </tr>
    </thead>
    <tbody>
    """

    for st in docs_list:
        sid = st["id"]
        nm = st.get("name", "")
        ag = st.get("age", "")
        cl = st.get("class", "")
        dv = st.get("division", "")  # Added division
        ad = st.get("address", "")
        ph = st.get("phone", "")
        gn = st.get("guardian_name", "")
        gp = st.get("guardian_phone", "")
        at = st.get("attendance", "")
        gr = st.get("grades", "")
        if isinstance(gr, dict):
            gr = json.dumps(gr)

        row = f"""
    <tr>
      <td style="color:#555; user-select:none;">{sid}</td>
      <td contenteditable="true">{nm}</td>
      <td contenteditable="true">{ag}</td>
      <td contenteditable="true">{cl}</td>
      <td contenteditable="true">{dv}</td> <!-- Division Cell -->
      <td contenteditable="true">{ad}</td>
      <td contenteditable="true">{ph}</td>
      <td contenteditable="true">{gn}</td>
      <td contenteditable="true">{gp}</td>
      <td contenteditable="true">{at}</td>
      <td contenteditable="true">{gr}</td>
      <td>
        <button class="btn btn-danger btn-delete-row" onclick="deleteRow('{sid}')">🗑️</button>
      </td>
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
# 13. Grades Functions
###############################################################################
def add_grade(params):
    subject = params.get("subject")
    if not subject:
        return {"error": "Missing 'subject'."}, 400
    grades = params.get("grades") or {}
    doc_id = subject.lower().replace(" ", "_")  # Simple doc ID generation
    doc = {
        "subject": subject,
        "grades": grades  # e.g., {"student_id1": {"term1": 85, "term2": 90, "term3": 88}, ...}
    }
    db.collection("grades").document(doc_id).set(doc)
    log_activity("ADD_GRADE", f"Added subject {subject} with ID {doc_id}")
    conf = comedic_confirmation("add_grade", name=subject, doc_id=doc_id)
    return {"message": f"{conf} (ID: {doc_id})"}, 200

def update_grade(params):
    subject_id = params.get("subject_id")
    student_id = params.get("student_id")
    term = params.get("term")
    marks = params.get("marks")

    if not all([subject_id, student_id, term, marks is not None]):
        return {"error": "Missing required fields."}, 400

    ref = db.collection("grades").document(subject_id)
    snap = ref.get()
    if not snap.exists():
        return {"error": f"No subject with ID {subject_id} found."}, 404

    grades = snap.to_dict().get("grades", {})
    student_grades = grades.get(student_id, {})
    old_marks = student_grades.get(term, None)
    student_grades[term] = marks
    grades[student_id] = student_grades

    ref.update({"grades": grades})
    log_activity("UPDATE_GRADE", f"Updated subject {subject_id}, student {student_id}, term {term} to {marks}")
    conf = comedic_confirmation("update_grade", doc_id=subject_id)
    return {"message": conf}, 200

def delete_grade(params):
    subject_id = params.get("subject_id")
    student_id = params.get("student_id")

    if not all([subject_id, student_id]):
        return {"error": "Missing 'subject_id' or 'student_id'."}, 400

    ref = db.collection("grades").document(subject_id)
    snap = ref.get()
    if not snap.exists():
        return {"error": f"No subject with ID {subject_id} found."}, 404

    grades = snap.to_dict().get("grades", {})
    if student_id in grades:
        del grades[student_id]
        ref.update({"grades": grades})
        log_activity("DELETE_GRADE", f"Deleted grades for student {student_id} in subject {subject_id}")
        conf = comedic_confirmation("delete_grade", doc_id=subject_id)
        return {"message": conf}, 200
    else:
        return {"error": f"No grades found for student {student_id} in subject {subject_id}."}, 404

def view_grades(params):
    """
    View grades, optionally filtered by subject.
    """
    subject = params.get("subject")
    if subject:
        query = db.collection("grades").where("subject", "==", subject)
    else:
        query = db.collection("grades")

    grades_docs = query.stream()
    grades_list = []
    for d in grades_docs:
        grade = d.to_dict()
        grade["subject_id"] = d.id
        grades_list.append(grade)

    if not grades_list:
        return "<p>No grades found.</p>"

    html = f"""
<div id="gradesSection" class="slideFromRight">
  <h4>Student Grades</h4>
  <table class="table table-bordered table-sm">
    <thead class="table-light">
      <tr>
        <th>Subject ID</th>
        <th>Subject Name</th>
        <th>Student ID</th>
        <th>Term 1</th>
        <th>Term 2</th>
        <th>Term 3</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
    """

    for grade in grades_list:
        subject_id = grade.get("subject_id", "")
        subject_name = grade.get("subject", "")
        grades = grade.get("grades", {})
        for student_id, terms in grades.items():
            term1 = terms.get("term1", "")
            term2 = terms.get("term2", "")
            term3 = terms.get("term3", "")
            row = f"""
    <tr>
      <td>{subject_id}</td>
      <td>{subject_name}</td>
      <td>{student_id}</td>
      <td contenteditable="true">{term1}</td>
      <td contenteditable="true">{term2}</td>
      <td contenteditable="true">{term3}</td>
      <td>
        <button class="btn btn-danger btn-delete-grade" onclick="deleteGrade('{subject_id}', '{student_id}')">🗑️</button>
      </td>
    </tr>
            """
            html += row

    html += """
    </tbody>
  </table>
  <button class="btn btn-success" onclick="saveGradesEdits()">Save Grades</button>
</div>
"""
    return html

###############################################################################
# 14. State Handling
###############################################################################
def handle_state_machine(user_prompt):
    st = conversation_context["state"]
    pend = conversation_context["pending_params"]
    delete_candidates = conversation_context.get("delete_candidates", [])

    # Handle states requiring additional information
    if st == STATE_AWAITING_DELETE_CHOICE:
        chosen = interpret_delete_choice(user_prompt, delete_candidates)
        conversation_context["state"] = STATE_IDLE
        conversation_context["delete_candidates"] = []
        if not chosen:
            return "I can't interpret your choice. (Try 'first', 'second', or an actual ID)."
        ok, msg = delete_student_doc(chosen)
        if not ok:
            return msg
        log_activity("DELETE_STUDENT", f"Deleted {chosen} after choice.")
        conf = comedic_confirmation("delete_student", doc_id=chosen)
        return conf

    elif st == STATE_AWAITING_VIEW_FILTER:
        # Expecting class and division
        filters = extract_filters(user_prompt)
        if not filters.get("class") or not filters.get("division"):
            missing = []
            if not filters.get("class"):
                missing.append("'class'")
            if not filters.get("division"):
                missing.append("'division'")
            return f"I still need the student's {' and '.join(missing)}. Please provide them or type 'cancel'."

        sclass = filters.get("class")
        division = filters.get("division")
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None

        return build_students_table_html(f"Displaying students for Class {sclass} Division {division}:", sclass, division)

    else:
        # IDLE state: classify and handle actions
        c = classify_casual_or_firestore(user_prompt)
        if c.get("type") == "casual":
            r = model.generate_content(user_prompt)
            if r.candidates:
                return r.candidates[0].content.parts[0].text.strip()
            else:
                return "I'm out of words..."

        elif c.get("type") == "firestore":
            a = c.get("action", "")
            p = c.get("parameters", {})
            if a == "view_students":
                # Check if class and division filter is applied
                sclass = p.get("class")
                division = p.get("division")
                if sclass and division:
                    return build_students_table_html(f"Displaying students for Class {sclass} Division {division}:", sclass, division)
                elif sclass or division:
                    # If only one filter is provided, prompt for the other
                    conversation_context["state"] = STATE_AWAITING_VIEW_FILTER
                    conversation_context["pending_params"] = p
                    conversation_context["last_intended_action"] = "view_students"
                    missing = []
                    if not sclass:
                        missing.append("'class'")
                    if not division:
                        missing.append("'division'")
                    return f"I need the student's {' and '.join(missing)} to filter. Please provide them or type 'cancel'."

            elif a == "add_student":
                # Ensure both 'name', 'class', and 'division' are provided
                if not p.get("name") or not p.get("class") or not p.get("division"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = p
                    conversation_context["last_intended_action"] = "add_student"
                    missing = []
                    if not p.get("name"):
                        missing.append("'name'")
                    if not p.get("class"):
                        missing.append("'class'")
                    if not p.get("division"):
                        missing.append("'division'")
                    return f"I need the student's {' ,'.join(missing)}. Please provide them or type 'cancel'."
                out, sts_code = add_student(p)
                if sts_code == 200 and "message" in out:
                    # Comedic
                    funny = f"Write a short witty statement acknowledging we have a new student '{p['name']}'. " \
                            f"Ask if they'd like to add details like marks or attendance. Under 40 words, humorous."
                    r2 = model.generate_content(funny)
                    if r2.candidates:
                        t = r2.candidates[0].content.parts[0].text.strip()
                        return out["message"] + "\n\n" + t
                    else:
                        return out["message"]
                else:
                    return out.get("error", "Error adding student.")

            elif a == "update_student":
                return handle_update_student(p)

            elif a == "delete_student":
                # Check if ID is provided
                sid = p.get("id")
                if sid:
                    ok, msg = delete_student_doc(sid)
                    if not ok:
                        return "No doc with that ID found."
                    log_activity("DELETE_STUDENT", f"Deleted {sid} directly.")
                    conf = comedic_confirmation("delete_student", doc_id=sid)
                    return conf
                # Else, check if name is provided
                nm = p.get("name")
                if not nm:
                    return "We need an ID or name to delete."
                matches = search_students_by_name(nm)
                if not matches:
                    return f"No student named {nm} found."
                if len(matches) == 1:
                    found_id = matches[0]["id"]
                    ok, msg = delete_student_doc(found_id)
                    if not ok:
                        return "No doc with that ID found."
                    log_activity("DELETE_STUDENT", f"Deleted {found_id}")
                    conf = comedic_confirmation("delete_student", doc_id=found_id)
                    return conf
                else:
                    conversation_context["state"] = STATE_AWAITING_DELETE_CHOICE
                    conversation_context["delete_candidates"] = matches
                    lines = []
                    for i, m in enumerate(matches):
                        lines.append(f"{i+1}. ID={m['id']} (class={m.get('class','')}{m.get('division','')}, age={m.get('age','')})")
                    listing = "\n".join(lines)
                    return f"Multiple matches for {nm}:\n{listing}\nWhich one to delete? ('first','second', or the ID)."

            elif a == "cleanup_data":
                return cleanup_data()

            elif a == "view_grades":
                # Optionally, accept subject filter
                subject = p.get("subject")
                return view_grades({"subject": subject})

            elif a == "add_grade":
                return add_grade(p)

            elif a == "update_grade":
                return update_grade(p)

            elif a == "delete_grade":
                return delete_grade(p)

            else:
                return f"Unknown Firestore action: {a}"

        else:
            return "I'm not sure what you're asking."

def handle_update_student(p):
    return update_student(p)

###############################################################################
# 15. Additional Routes
###############################################################################
@app.route("/delete_by_id", methods=["POST"])
def delete_by_id():
    data = request.json
    sid = data.get("id")
    if not sid:
        return jsonify({"error": "No ID"}), 400
    ok, msg = delete_student_doc(sid)
    if not ok:
        return jsonify({"error": msg}), 404
    log_activity("DELETE_STUDENT", f"Deleted {sid} via trash icon.")
    conf = comedic_confirmation("delete_student", doc_id=sid)
    return jsonify({"success": True, "message": conf}), 200

@app.route("/bulk_update_students", methods=["POST"])
def bulk_update_students_route():
    data = request.json
    ups = data.get("updates", [])
    if not ups:
        return jsonify({"error": "No updates provided."}), 400
    updated = []
    for st in ups:
        sid = st.get("id")
        if not sid:
            continue
        doc_ref = db.collection("students").document(sid)
        snap = doc_ref.get()
        if not snap.exists():
            continue
        # Update fields
        fields_to_update = {}
        for k, v in st.items():
            if k == "id":
                continue
            if k == "age":
                fields_to_update["age"] = _safe_int(v)
            else:
                fields_to_update[k] = v
        doc_ref.update(fields_to_update)
        updated.append(sid)
    if updated:
        log_activity("BULK_UPDATE", f"Updated => {updated}")
    return jsonify({"success": True, "updated_ids": updated}), 200

###############################################################################
# 16. Grades Routes
###############################################################################
@app.route("/add_grade", methods=["POST"])
def add_grade_route():
    data = request.json
    out, sts_code = add_grade(data)
    if sts_code == 200:
        return jsonify({"message": out["message"]}), 200
    else:
        return jsonify({"error": out.get("error", "Failed to add grade.")}), sts_code

@app.route("/update_grade", methods=["POST"])
def update_grade_route():
    data = request.json
    out, sts_code = update_grade(data)
    if sts_code == 200:
        return jsonify({"message": out["message"]}), 200
    else:
        return jsonify({"error": out.get("error", "Failed to update grade.")}), sts_code

@app.route("/delete_grade", methods=["POST"])
def delete_grade_route():
    data = request.json
    out, sts_code = delete_grade(data)
    if sts_code == 200:
        return jsonify({"message": out["message"]}), 200
    else:
        return jsonify({"error": out.get("error", "Failed to delete grade.")}), sts_code

@app.route("/view_grades", methods=["GET"])
def view_grades_route():
    subject = request.args.get("subject")
    return view_grades({"subject": subject})

###############################################################################
# 17. The main HTML route with chat interface
###############################################################################
@app.route("/")
def index():
    global welcome_summary
    # We'll embed the comedic summary as the first AI message in the chat
    return render_template("index.html", summary=welcome_summary)

###############################################################################
# 18. Process Prompt Route
###############################################################################
@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    data = request.json
    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "No prompt provided."}), 400

    # Handle state machine
    response_message = handle_state_machine(prompt)

    # Append to conversation memory
    conversation_memory.append({"role": "user", "content": prompt})
    conversation_memory.append({"role": "assistant", "content": response_message})

    # Trim memory if exceeds
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory.pop(0)

    save_memory_to_firestore()

    return jsonify({"message": response_message}), 200

###############################################################################
# 19. Helper Function to Extract Filters
###############################################################################
def extract_filters(user_prompt):
    """
    A simple parser to extract 'class' and 'division' from user prompt.
    This can be enhanced with more sophisticated NLP techniques.
    """
    filters = {}
    # Example parsing logic (needs to be improved for real-world use)
    # Look for patterns like 'class 10A' or 'class 10' and 'division A'
    class_match = re.search(r'class\s*(\d+)', user_prompt.lower())
    division_match = re.search(r'division\s*([a-zA-Z])', user_prompt.lower())
    if class_match:
        filters['class'] = class_match.group(1)
    if division_match:
        filters['division'] = division_match.group(1)
    return filters

###############################################################################
# 20. Actually run Flask
###############################################################################
if __name__ == "__main__":
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

    app.run(debug=True, port=8000)
