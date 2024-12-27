import re
import os
import json
import uuid
import logging
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

###############################################################################
# 4. Firebase Initialization (Service Account Credentials)
###############################################################################
if not firebase_admin._apps:
    service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    if not service_account_path or not os.path.exists(service_account_path):
        raise EnvironmentError("FIREBASE_SERVICE_ACCOUNT_PATH environment variable not set or file does not exist.")
    try:
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        raise Exception(f"Error initializing Firebase: {e}")

db = firestore.client()
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
        # Since there's no user authentication, we'll store memory in a single document
        db.collection('conversation_memory').document('global').set({
            "memory": conversation_memory,
            "context": conversation_context
        })
        logging.info("✅ Memory saved to Firestore.")
    except Exception as e:
        logging.error(f"❌ Failed to save memory: {e}")

def load_memory_from_firestore():
    try:
        doc = db.collection('conversation_memory').document('global').get()
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
# 7. Utility Functions
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
    """
    For each entry, update the Firestore document with the given ID in the 'students' collection.
    """
    updated_ids = []
    for st in student_list:
        sid = st.get("id")
        if not sid:
            continue
        doc_ref = db.collection("students").document(sid)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            logging.warning(f"Document not found for ID {sid} in 'students' collection.")
            continue

        # Validate required fields
        if not st.get("name") or not st.get("class") or not st.get("division") or not isinstance(st.get("age"), int):
            logging.warning(f"Invalid data for student ID {sid}. Skipping update.")
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
# 9. Cleanup Data (Deduplicate + remove docs w/o 'id')
###############################################################################
def cleanup_data():
    docs = db.collection("students").stream()
    # Store actual doc.id so we can remove docs
    students = []
    doc_map = {}
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id  # Firestore doc ID
        doc_map[doc.id] = doc  # Keep doc reference
        students.append(data)

    from collections import defaultdict
    name_groups = defaultdict(list)

    # Remove documents missing a name
    no_name_deleted = []
    for st in students:
        doc_id = st.get("id")
        if not doc_id:
            continue  # Firestore documents always have IDs
        name = st.get("name", "").strip().lower()
        if not name:
            # Delete document
            try:
                doc_map[doc_id].reference.delete()
                no_name_deleted.append(doc_id)
            except Exception as e:
                logging.error(f"Error deleting doc {doc_id} with no name: {e}")
            continue
        # Group by name
        name_groups[name].append(st)

    # Remove duplicates, keeping the most complete document
    duplicates_deleted = []
    for name, group in name_groups.items():
        if len(group) > 1:
            # Sort by number of non-empty fields descending
            sorted_group = sorted(group, key=lambda x: sum(1 for v in x.values() if v not in [None, "", {}]), reverse=True)
            # Keep the first (most complete), delete the rest
            for duplicate in sorted_group[1:]:
                dup_id = duplicate["id"]
                try:
                    doc_map[dup_id].reference.delete()
                    duplicates_deleted.append(dup_id)
                except Exception as e:
                    logging.error(f"Error deleting duplicate doc {dup_id}: {e}")

    # Log cleanup activities
    if no_name_deleted:
        log_activity("CLEANUP_DATA", f"Removed {len(no_name_deleted)} docs missing name => {no_name_deleted}")
    if duplicates_deleted:
        log_activity("CLEANUP_DATA", f"Deleted duplicates => {duplicates_deleted}")

    return build_students_table_html("Data cleaned! Updated student records below:")

###############################################################################
# 10. Building an Editable Table
###############################################################################
def build_students_table_html(heading="Student Records"):
    """
    Build an HTML table for displaying student records.
    """
    try:
        all_docs = db.collection("students").stream()
        students = []
        classes_set = set()
        for doc in all_docs:
            st = doc.to_dict()
            st["id"] = doc.id  # Firestore doc ID
            students.append(st)
            if st.get("class") and st.get("division"):
                combined = f"{st['class']}{st['division']}"
                classes_set.add(combined)

        if not students:
            logging.info("No students found in Firestore.")
            return "<p>No students found.</p>"

        html = f"""
        <div id="studentsSection" class="animate__animated animate__fadeIn">
          <h4>{heading}</h4>
          <table class="table table-bordered table-sm">
            <thead class="table-light">
              <tr>
                <th>ID</th>
                <th contenteditable="false">Name</th>
                <th contenteditable="false">Age</th>
                <th contenteditable="false">Class</th>
                <th contenteditable="false">Division</th>
                <th contenteditable="false">Address</th>
                <th contenteditable="false">Phone</th>
                <th contenteditable="false">Guardian</th>
                <th contenteditable="false">Guardian Phone</th>
                <th contenteditable="false">Attendance</th>
                <th contenteditable="false">Grades</th>
                <th>Actions</th> <!-- Header for Actions -->
              </tr>
            </thead>
            <tbody>
        """
        for st in students:
            sid = st.get("id", "")
            name = st.get("name", "")
            age = st.get("age", "")
            sclass = st.get("class", "")
            division = st.get("division", "")
            address = st.get("address", "")
            phone = st.get("phone", "")
            guardian_name = st.get("guardian_name", "")
            guardian_phone = st.get("guardian_phone", "")
            attendance = st.get("attendance", "")
            grades = st.get("grades", "")

            # Convert dict => JSON
            if isinstance(grades, dict):
                grades = json.dumps(grades)

            row_html = f"""
            <tr>
              <td class="student-id" style="color:#555; user-select:none;">{sid}</td>
              <td contenteditable="true">{name}</td>
              <td contenteditable="true">{age}</td>
              <td contenteditable="true" class="class-cell">{sclass}</td>
              <td contenteditable="true" class="division-cell">{division}</td>
              <td contenteditable="true">{address}</td>
              <td contenteditable="true">{phone}</td>
              <td contenteditable="true">{guardian_name}</td>
              <td contenteditable="true">{guardian_phone}</td>
              <td contenteditable="true">{attendance}</td>
              <td contenteditable="true">{grades}</td>
              <td>
                <button class="btn btn-danger btn-delete-row" aria-label="Delete Row">
                  <i class="fas fa-trash-alt"></i>
                </button>
              </td>
            </tr>
            """
            html += row_html

        html += """
            </tbody>
          </table>
          <button class="btn btn-success mt-3" onclick="saveTableEdits()" aria-label="Save Changes">Save Changes</button>
        </div>
        """
        logging.info(f"Built students table with {len(students)} entries.")
        return html
    except Exception as e:
        logging.error(f"Error building students table: {e}")
        return "<p>Error loading student records.</p>"

###############################################################################
# 11. Student Logic (Add, Update, Delete, Analytics)
###############################################################################
def generate_student_id(name, age):
    unique_suffix = uuid.uuid4().hex[:6].upper()  # Generates a unique 6-character suffix
    name_part = (name[:3].upper() if len(name) >= 3 else name.upper())
    age_str = f"{age:02}" if age else "00"
    return f"{name_part}{age_str}{unique_suffix}"

def create_funny_prompt_for_new_student(name):
    return (
        f"Write a short witty statement acknowledging we have a new student '{name}'. "
        "Ask if they'd like to add details like marks or attendance. Under 40 words, humorous."
    )

def create_comedic_confirmation(action, name=None, student_id=None):
    if action == "add_student":
        prompt = f"Generate a short, darkly funny success message confirming the addition of {name} (ID {student_id})."
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
        return "Action completed in the shadows..."

def add_student(params):
    try:
        name = params.get("name")
        sclass = params.get("class")
        division = params.get("division")
        if not name or not sclass or not division:
            return {"error": "Missing 'name', 'class', or 'division' to add student."}, 400
        age = _safe_int(params.get("age"))
        # Check if ID is provided; if not, generate one
        sid = params.get("id") or generate_student_id(name, age)
        doc_data = {
            "id": sid,
            "name": name,
            "age": age,
            "class": sclass,
            "division": division,
            "address": params.get("address"),
            "phone": params.get("phone"),
            "guardian_name": params.get("guardian_name"),
            "guardian_phone": params.get("guardian_phone"),
            "attendance": params.get("attendance"),
            "grades": params.get("grades") or {},
            "grades_history": []
        }
        db.collection("students").document(sid).set(doc_data)
        log_activity("ADD_STUDENT", f"Added {name} => {sid}")
        conf = create_comedic_confirmation("add_student", name, sid)
        return {"message": f"{conf} (ID: {sid})"}, 200
    except Exception as e:
        logging.error(f"Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    try:
        sid = params.get("id")
        if not sid:
            return {"error": "Missing 'id' for update."}, 400
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
                hist = snap.to_dict().get("grades_history", [])
                hist.append({
                    "old_grades": old_grades,
                    "new_grades": v,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                update_fields["grades_history"] = hist
            update_fields[k] = v
        # Validation: Ensure 'name', 'class', and 'division' are not empty
        if 'name' in update_fields and not update_fields['name']:
            return {"error": "The 'name' field cannot be empty."}, 400
        if 'class' in update_fields and not update_fields['class']:
            return {"error": "The 'class' field cannot be empty."}, 400
        if 'division' in update_fields and not update_fields['division']:
            return {"error": "The 'division' field cannot be empty."}, 400
        doc_ref.update(update_fields)
        log_activity("UPDATE_STUDENT", f"Updated {sid} with {update_fields}")
        c = create_comedic_confirmation("update_student", student_id=sid)
        return {"message": c}, 200
    except Exception as e:
        logging.error(f"update_student error: {e}")
        return {"error": str(e)}, 500

def delete_student(params):
    try:
        sid = params.get("id")
        if not sid:
            return {"error": "Missing 'id' for delete."}, 400
        doc_ref = db.collection("students").document(sid)
        if not doc_ref.get().exists:
            return {"error": f"No doc with id {sid}."}, 404
        doc_ref.delete()
        log_activity("DELETE_STUDENT", f"Deleted {sid}")
        c = create_comedic_confirmation("delete_student", student_id=sid)
        return {"message": c}, 200
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

        def avg_marks(g):
            if not isinstance(g, dict):
                return 0
            vals = [x for x in g.values() if isinstance(x, (int, float))]
            return sum(vals) / len(vals) if vals else 0

        oldest = hist[0]["old_grades"]
        newest = hist[-1]["new_grades"]
        old_avg = avg_marks(oldest)
        new_avg = avg_marks(newest)
        t = "improved" if new_avg > old_avg else "declined" if new_avg < old_avg else "stayed the same"
        msg = f"{data['name']}'s performance has {t}. Old Avg: {old_avg}, New Avg: {new_avg}"
        return {"message": msg}, 200
    except Exception as e:
        logging.error(f"analytics_student error: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 12. Classification for "Casual" vs "Firestore"
###############################################################################
def classify_casual_or_firestore(user_prompt):
    prompt = (
        "You are an advanced assistant that decides if the user prompt is casual or a Firestore operation.\n"
        "If casual => {\"type\":\"casual\"}\n"
        "If firestore => {\"type\":\"firestore\",\"action\":\"...\",\"parameters\":{...}}\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student.\n"
        f"User Prompt:'{user_prompt}'\n"
        "Output JSON only."
    )
    resp = model.generate_content(prompt)
    if not resp.candidates:
        return {"type": "casual"}
    raw = resp.candidates[0].content.parts[0].text.strip()
    raw = remove_code_fences(raw)
    try:
        data = json.loads(raw)
        if "type" not in data:
            data["type"] = "casual"
        return data
    except json.JSONDecodeError:
        return {"type": "casual"}

###############################################################################
# 13. Additional Field Extraction
###############################################################################
def extract_fields(user_input, desired_fields):
    p = (
        f"You are an assistant that extracts fields from user input.\n"
        f"Fields: {', '.join(desired_fields)}\n"
        f"User Input:'{user_input}'\n"
        "Return JSON with only those fields.\n"
    )
    resp = model.generate_content(p)
    if not resp.candidates:
        return {}
    raw = ''.join(part.text for part in resp.candidates[0].content.parts).strip()
    raw = remove_code_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
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
            params["id"] = matches[0].get("id")
            out, sts = analytics_student(params)
            return out.get("message", out.get("error", "Error."))
        else:
            listing = "\n".join([f"{m.get('id')}: {m.get('name')}" for m in matches if m.get("id")])
            return f"Multiple students found:\n{listing}\nPlease provide the ID."
    else:
        return "Which student? Please provide the ID or name."

###############################################################################
# 15. The Main State Machine
###############################################################################
def handle_state_machine(user_prompt):
    st = conversation_context["state"]
    pend = conversation_context["pending_params"]

    # Handle states requiring additional information
    if st == STATE_AWAITING_STUDENT_INFO:
        desired = ["name", "age", "class", "division", "address", "phone", "guardian_name", "guardian_phone", "attendance", "grades"]
        found = extract_fields(user_prompt, desired)
        for k, v in found.items():
            pend[k] = v
        if not pend.get("name") or not pend.get("class") or not pend.get("division"):
            missing = []
            if not pend.get("name"):
                missing.append("'name'")
            if not pend.get("class"):
                missing.append("'class'")
            if not pend.get("division"):
                missing.append("'division'")
            return f"I still need the student's {' ,'.join(missing)}. Please provide them or type 'cancel'."

        out, status = add_student(pend)
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        if status == 200 and "message" in out:
            funny_p = create_funny_prompt_for_new_student(pend["name"])
            r2 = model.generate_content(funny_p)
            if r2.candidates:
                tx = r2.candidates[0].content.parts[0].text.strip()
                return out["message"] + "\n\n" + tx
            else:
                return out["message"]
        else:
            return out.get("error", "Error adding student.")

    elif st == STATE_AWAITING_ANALYTICS_TARGET:
        desired = ["id", "name"]
        found = extract_fields(user_prompt, desired)
        for k, v in found.items():
            pend[k] = v
        if pend.get("id"):
            out, stat = analytics_student(pend)
            conversation_context["state"] = STATE_IDLE
            conversation_context["pending_params"] = {}
            conversation_context["last_intended_action"] = None
            return out.get("message", out.get("error", "Error."))
        elif pend.get("name"):
            docs = db.collection("students").where("name", "==", pend["name"]).stream()
            matches = [d.to_dict() for d in docs]
            if not matches:
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return f"No student named {pend['name']}."
            if len(matches) == 1:
                pend["id"] = matches[0].get("id")
                out, sts = analytics_student(pend)
                conversation_context["state"] = STATE_IDLE
                conversation_context["pending_params"] = {}
                conversation_context["last_intended_action"] = None
                return out.get("message", out.get("error", "Error."))
            else:
                listing = "\n".join([f"{m.get('id')}: {m.get('name')}" for m in matches if m.get("id")])
                return f"Multiple students found:\n{listing}\nPlease provide the ID."
        else:
            return "Which student? Please provide the ID or name."

    else:
        # IDLE state: classify and handle actions
        c = classify_casual_or_firestore(user_prompt)
        if c.get("type") == "casual":
            r = model.generate_content(user_prompt)
            if r.candidates:
                return r.candidates[0].content.parts[0].text.strip()
            else:
                return "I have nothing to say."
        elif c.get("type") == "firestore":
            a = c.get("action", "")
            p = c.get("parameters", {})
            if a == "view_students":
                # Check if class and division filter is applied
                cls = p.get("class")
                div = p.get("division")
                if cls and div:
                    heading = f"Student Records for Class {cls}{div}"
                else:
                    heading = "Student Records"
                return build_students_table_html(heading)
            elif a == "cleanup_data":
                return cleanup_data()
            elif a == "add_student":
                if not p.get("name") or not p.get("class") or not p.get("division"):
                    conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                    conversation_context["pending_params"] = p
                    conversation_context["last_intended_action"] = "add_student"
                    return "Let's add a new student. What's their name, class, and division?"
                out, sts = add_student(p)
                if sts == 200 and "message" in out:
                    funny = create_funny_prompt_for_new_student(p["name"])
                    rr = model.generate_content(funny)
                    if rr.candidates:
                        tx = rr.candidates[0].content.parts[0].text.strip()
                        return out["message"] + "\n\n" + tx
                    else:
                        return out["message"]
                else:
                    return out.get("error", "Error adding student.")
            elif a == "update_student":
                if not p.get("id"):
                    return "To update, we need an 'id'. Please provide the student's ID."
                out, sts = update_student(p)
                return out.get("message", out.get("error", "Error."))
            elif a == "delete_student":
                if not p.get("id"):
                    return "We need the 'id' to delete a student."
                out, sts = delete_student(p)
                return out.get("message", out.get("error", "Error."))
            elif a == "analytics_student":
                if not (p.get("id") or p.get("name")):
                    conversation_context["state"] = STATE_AWAITING_ANALYTICS_TARGET
                    conversation_context["pending_params"] = p
                    conversation_context["last_intended_action"] = "analytics_student"
                    return "Which student do you want to analyze? Please provide the ID or name."
                else:
                    return handle_analytics_call(p)
            else:
                return f"Unknown Firestore action: {a}"
        else:
            return "I'm not sure. Is it casual or a Firestore request?"

###############################################################################
# 16. Flask Routes and HTML Rendering
###############################################################################
@app.route("/")
def index():
    """
    Render the Home Screen with summary and a "Continue" button.
    Upon clicking "Continue", the Home Screen fades out and the chatbot interface appears.
    """
    mem, ctx = load_memory_from_firestore()
    if mem:
        conversation_memory.extend(mem)
    if ctx:
        conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    global welcome_summary
    welcome_summary = summary  # Show this on the Home Screen
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    return render_template("index.html", safe_summary=welcome_summary)

###############################################################################
# 17. Bulk Update Route
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
# 18. Get Unique Class-Division Route
###############################################################################
@app.route("/get_unique_class_divisions", methods=["GET"])
def get_unique_class_divisions_route():
    try:
        # Fetch unique class-division combinations
        all_docs = db.collection("students").stream()
        class_div_set = set()
        for doc in all_docs:
            st = doc.to_dict()
            cls = st.get("class")
            div = st.get("division")
            if cls and div:
                combined = f"{cls}{div}"
                class_div_set.add(combined)
        return jsonify({"class_divisions": sorted(list(class_div_set))}), 200
    except Exception as e:
        logging.error(f"❌ Error fetching unique class-divisions: {e}")
        return jsonify({"error": "Failed to fetch class-divisions."}), 500

###############################################################################
# 19. Grades Management Routes
###############################################################################
@app.route("/get_grades", methods=["GET"])
def get_grades():
    try:
        grades_docs = db.collection("grades").stream()
        grades = []
        for doc in grades_docs:
            grade = doc.to_dict()
            grade["subject_id"] = doc.id
            grades.append(grade)
        return jsonify({"grades": grades}), 200
    except Exception as e:
        logging.error(f"❌ Error fetching grades: {e}")
        return jsonify({"error": "Failed to fetch grades."}), 500

@app.route("/update_grades", methods=["POST"])
def update_grades():
    try:
        data = request.json
        subject_id = data.get("subject_id")
        student_id = data.get("student_id")
        term = data.get("term")
        marks = data.get("marks")

        if not all([subject_id, student_id, term, marks is not None]):
            return jsonify({"error": "Missing required fields."}), 400

        doc_ref = db.collection("grades").document(subject_id)
        doc = doc_ref.get()
        if not doc.exists:
            # Create the subject document if it doesn't exist
            doc_ref.set({"subject_name": data.get("subject_name", "Unknown")})

        # Update the marks
        doc_ref.update({
            f"marks.{student_id}.{term}": marks
        })

        log_activity("UPDATE_GRADES", f"Subject: {subject_id}, Student: {student_id}, Term: {term}, Marks: {marks}")
        return jsonify({"message": "Grades updated successfully."}), 200
    except Exception as e:
        logging.error(f"❌ Error updating grades: {e}")
        return jsonify({"error": "Failed to update grades."}), 500

@app.route("/delete_grade", methods=["POST"])
def delete_grade():
    try:
        data = request.json
        subject_id = data.get("subject_id")
        student_id = data.get("student_id")

        if not all([subject_id, student_id]):
            return jsonify({"error": "Missing 'subject_id' or 'student_id'."}), 400

        doc_ref = db.collection("grades").document(subject_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": f"No subject with ID {subject_id} found."}), 404

        # Delete the student's marks
        doc_ref.update({
            f"marks.{student_id}": firestore.DELETE_FIELD
        })

        log_activity("DELETE_GRADE", f"Subject: {subject_id}, Student: {student_id}")
        return jsonify({"message": "Grade deleted successfully."}), 200
    except Exception as e:
        logging.error(f"❌ Error deleting grade: {e}")
        return jsonify({"error": "Failed to delete grade."}), 500

@app.route("/view_grades", methods=["GET"])
def view_grades():
    try:
        grades_docs = db.collection("grades").stream()
        grades = []
        for doc in grades_docs:
            grade = doc.to_dict()
            grade["subject_id"] = doc.id
            grades.append(grade)
        return jsonify({"grades": grades}), 200
    except Exception as e:
        logging.error(f"❌ Error viewing grades: {e}")
        return jsonify({"error": "Failed to view grades."}), 500

###############################################################################
# 20. Authentication Routes
###############################################################################
# Since we're removing authentication, these routes are no longer needed.

###############################################################################
# 21. Main Conversation Route
###############################################################################
@app.route("/process_prompt", methods=["POST"])
def process_prompt_route():
    global conversation_memory, conversation_context
    data = request.json
    user_prompt = data.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "No prompt provided."}), 400

    # Append user prompt to memory
    conversation_memory.append({"role": "user", "content": user_prompt})
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory = conversation_memory[-MAX_MEMORY:]

    # Handle reset commands
    if user_prompt.lower() in ["reset memory", "reset conversation", "cancel"]:
        conversation_memory.clear()
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["last_intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    # Process the user prompt through the state machine
    reply = handle_state_machine(user_prompt)
    # Append AI reply to memory
    conversation_memory.append({"role": "AI", "content": reply})
    save_memory_to_firestore()
    return jsonify({"message": reply}), 200

###############################################################################
# 22. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exc(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 23. On Startup => Load Memory + Summaries
###############################################################################
@app.before_first_request
def load_on_start():
    mem, ctx = load_memory_from_firestore()
    if mem:
        conversation_memory.extend(mem)
    if ctx:
        conversation_context.update(ctx)

###############################################################################
# 24. Run the Flask Application
###############################################################################
if __name__ == "__main__":
    app.run(debug=True, port=8000)
