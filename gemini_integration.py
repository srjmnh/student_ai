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
    if not snap.exists:
        return False, "No doc with that ID."
    ref.delete()
    return True, "deleted"

###############################################################################
# 9. Student Functions
###############################################################################
def gen_student_id(name, age):
    r = random.randint(1000, 9999)
    part = (name[:4].upper() if len(name) >= 4 else name.upper())
    a = str(age) if age else "00"
    return f"{part}{a}{r}"

def comedic_confirmation(action, name=None, doc_id=None):
    if action == "add_student":
        pr = f"Generate a short, darkly funny success confirming new student {name} ID {doc_id}."
    elif action == "delete_student":
        pr = f"Create a short, darkly witty message confirming the deletion of ID {doc_id}."
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
    sid = gen_student_id(name, age)
    doc = {
        "id": sid,
        "name": name,
        "age": age,
        "class": params.get("class"),
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
    if not snap.exists:
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
    if not snap.exists:
        return {"error": f"No doc with id {sid}."}, 404
    # Minimal stub
    return {"message": "(Analytics not fully implemented)."}, 200

###############################################################################
# 10. Classification
###############################################################################
def classify_casual_or_firestore(prompt):
    cp = (
        "You are an advanced assistant that decides if the user prompt is casual or a Firestore operation.\n"
        "If casual => {\"type\":\"casual\"}\n"
        "If firestore => {\"type\":\"firestore\",\"action\":\"...\",\"parameters\":{...}}\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student.\n"
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
    We'll read docs from Firestore, store doc.id in each record => doc["id"],
    remove duplicates by name (highest field count), remove doc that have no name or blank name
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

def build_students_table_html(heading="Student Records"):
    all_docs = db.collection("students").stream()
    docs_list = []
    for d in all_docs:
        st = d.to_dict()
        st["id"] = d.id
        docs_list.append(st)

    if not docs_list:
        return "<p>No students found.</p>"

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

    for st in docs_list:
        sid = st["id"]
        nm = st.get("name", "")
        ag = st.get("age", "")
        cl = st.get("class", "")
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
      <td contenteditable="true">{ad}</td>
      <td contenteditable="true">{ph}</td>
      <td contenteditable="true">{gn}</td>
      <td contenteditable="true">{gp}</td>
      <td contenteditable="true">{at}</td>
      <td contenteditable="true">{gr}</td>
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
# 13. State Handling
###############################################################################
def handle_state_machine(user_prompt):
    st = conversation_context["state"]
    pend = conversation_context["pending_params"]
    delete_candidates = conversation_context.get("delete_candidates", [])

    # If we asked user which doc to delete
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

    # Otherwise normal classification
    c = classify_casual_or_firestore(user_prompt)
    if c["type"] == "casual":
        r = model.generate_content(user_prompt)
        if r.candidates:
            return r.candidates[0].content.parts[0].text.strip()
        else:
            return "I'm out of words..."

    elif c["type"] == "firestore":
        a = c.get("action", "")
        p = c.get("parameters", {})

        if a == "delete_student":
            # Check if ID is provided
            sid = p.get("id")
            if sid:
                ok, msg = delete_student_doc(sid)
                if not ok:
                    return "No doc with that ID found."
                log_activity("DELETE_STUDENT", f"Deleted {sid} directly.")
                cc = comedic_confirmation("delete_student", doc_id=sid)
                return cc
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
                    lines.append(f"{i+1}. ID={m['id']} (class={m.get('class','')}, age={m.get('age','')})")
                listing = "\n".join(lines)
                return f"Multiple matches for {nm}:\n{listing}\nWhich one to delete? ('first','second', or the ID)."

        elif a == "view_students":
            return build_students_table_html("Student Records")

        elif a == "cleanup_data":
            return cleanup_data()

        elif a == "add_student":
            return handle_add_student(p)

        elif a == "update_student":
            return handle_update_student(p)

        elif a == "analytics_student":
            return handle_analytics(p)

        else:
            return f"Unknown Firestore action: {a}"

    else:
        return "I'm not sure what you're asking."

def handle_add_student(p):
    n = p.get("name")
    if not n:
        conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
        conversation_context["pending_params"] = p
        conversation_context["last_intended_action"] = "add_student"
        return "Let's add a new student. What's their name?"
    out, st_code = add_student(p)
    if st_code == 200 and "message" in out:
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

def handle_update_student(p):
    out, st_code = update_student(p)
    return out.get("message", out.get("error", "Error."))

def handle_analytics(p):
    sid = p.get("id")
    nm = p.get("name")
    if not (sid or nm):
        conversation_context["state"] = STATE_AWAITING_ANALYTICS_TARGET
        conversation_context["pending_params"] = p
        conversation_context["last_intended_action"] = "analytics_student"
        return "Which student do you want to check? Provide ID or name."
    out, st_code = analytics_student(p)
    return out.get("message", out.get("error", "Error."))

###############################################################################
# 14. Additional Routes
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
        if not snap.exists:
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
# 15. The main HTML route with dark mode, intro screen, etc.
###############################################################################
@app.route("/")
def index():
    global welcome_summary
    # We'll embed the comedic summary in the f-string as "safe_sum"
    safe_sum = welcome_summary.replace('"', '\\"').replace('\n', '\\n')

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Super Student Management</title>
  <link rel="stylesheet" 
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
  <style>
    body {{
      margin:0; padding:0; background:#f8f9fa;
      transition: background 0.3s, color 0.3s;
    }}
    body.dark-mode {{
      background:#1d1d1d; color:#fafafa;
    }}
    #introScreen {{
      position:fixed; top:0; left:0; right:0; bottom:0;
      background:#111; color:#fff; display:flex; flex-direction:column;
      justify-content:center; align-items:center;
      text-align:center; padding:2rem; z-index:9999;
      transition: opacity 0.5s ease;
    }}
    #introScreen.hidden {{
      opacity:0; pointer-events:none;
    }}
    .chat-wrap {{
      max-width:700px; margin:2rem auto; background:#fff; 
      border-radius:0.5rem; box-shadow:0 4px 10px rgba(0,0,0,0.1);
      display:none; /* hidden until intro is closed */
      flex-direction:column; height:80vh; overflow:hidden;
      transition: transform 0.5s ease, background 0.3s, color 0.3s;
    }}
    body.dark-mode .chat-wrap {{
      background:#333; color:#fff;
    }}
    .chat-header {{
      background:#343a40; color:#fff; padding:1rem; text-align:center;
      display:flex; justify-content:space-between; align-items:center;
    }}
    .dark-toggle {{
      background:transparent; border:1px solid #fff; color:#fff; 
      border-radius:3px; padding:0.3rem 0.6rem; cursor:pointer;
    }}
    .dark-toggle:hover {{
      opacity:0.7;
    }}
    .chat-body {{
      flex:1; padding:1rem; overflow-y:auto; display:flex; flex-direction:column;
    }}
    .chat-bubble {{
      margin-bottom:0.75rem; padding:0.75rem 1rem; border-radius:15px; 
      max-width:75%; word-wrap:break-word; white-space:pre-wrap;
      transition: background 0.3s ease;
    }}
    .chat-bubble:hover {{
      background:#e2e2e2;
    }}
    body.dark-mode .chat-bubble:hover {{
      background:#444;
    }}
    .user-msg {{
      background:#007bff; color:#fff; align-self:flex-end; border-bottom-right-radius:0;
    }}
    .ai-msg {{
      background:#e9ecef; color:#000; align-self:flex-start; border-bottom-left-radius:0;
    }}
    body.dark-mode .ai-msg {{
      background:#555; color:#fff;
    }}
    .chat-footer {{
      border-top:1px solid #ddd; padding:1rem; background:#f8f9fa;
      transition: background 0.3s ease;
    }}
    body.dark-mode .chat-footer {{
      background:#444;
    }}
    #tablePanel {{
      position:fixed; top:0; right:0; width:50%; height:100%;
      background:#fff; border-left:1px solid #ccc; padding:1rem;
      overflow-y:auto; transform:translateX(100%); transition:transform 0.5s ease;
    }}
    #tablePanel.show {{
      transform:translateX(0%);
    }}
    #chatSection.slideLeft {{
      transform:translateX(-20%);
    }}
    td[contenteditable="true"] {{
      outline:1px dashed #ccc; 
      transition: background 0.3s ease;
    }}
    td[contenteditable="true"]:hover {{
      background:#fafbcd;
    }}
    @media (max-width:576px) {{
      .chat-wrap {{
        margin:1rem; height:85vh;
      }}
      .chat-bubble {{
        max-width:100%;
      }}
      #tablePanel {{
        width:100%;
      }}
      #chatSection.slideLeft {{
        transform:translateX(-10%);
      }}
    }}
  </style>
</head>
<body>
  <!-- Intro screen with comedic summary -->
  <div id="introScreen">
    <h1 style="font-size:1.5rem; max-width:600px; color:#fff;">
      “{safe_sum}”
    </h1>
    <button class="btn btn-light" onclick="hideIntro()">Continue</button>
  </div>

  <!-- Background music with random track from an array of URLs -->
  <audio id="bgMusic" autoplay loop></audio>

  <div class="chat-wrap" id="chatSection">
    <div class="chat-header">
      <h4 style="margin:0;">Student Management Chat</h4>
      <button class="dark-toggle" onclick="toggleDarkMode()">Dark Mode</button>
    </div>
    <div class="chat-body" id="chatBody"></div>
    <div class="chat-footer">
      <div class="input-group">
        <input type="text" class="form-control" id="userInput" placeholder="Ask me anything..."
               onkeydown="if(event.key==='Enter') sendPrompt();">
        <button class="btn btn-primary" onclick="sendPrompt()">Send</button>
      </div>
    </div>
  </div>

  <div id="tablePanel"></div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    function hideIntro() {
      console.log("hideIntro called!"); // for debugging
      const intro = document.getElementById('introScreen');
      intro.classList.add('hidden');
      setTimeout(() => {
        intro.style.display='none';
        // Now show chat
        const chatSection = document.getElementById('chatSection');
        chatSection.style.display='';
      }, 500);
    }

    function toggleDarkMode() {
      document.body.classList.toggle('dark-mode');
    }

    const musicTracks = [
      "https://www.bensound.com/bensound-music/bensound-anewbeginning.mp3",
      "https://www.bensound.com/bensound-music/bensound-ukulele.mp3",
      "https://www.bensound.com/bensound-music/bensound-funnysong.mp3"
    ];

    window.addEventListener('DOMContentLoaded', () => {
      // Hide chat by default
      const chatSection = document.getElementById('chatSection');
      chatSection.style.display='none';

      const bgMusic = document.getElementById('bgMusic');
      const randomUrl = musicTracks[Math.floor(Math.random() * musicTracks.length)];
      bgMusic.src = randomUrl;
    });

    const chatBody = document.getElementById('chatBody');
    const userInput = document.getElementById('userInput');
    const tablePanel = document.getElementById('tablePanel');

    function addBubble(text, isUser=false) {
      const bubble = document.createElement('div');
      bubble.classList.add('chat-bubble', isUser ? 'user-msg' : 'ai-msg');
      bubble.innerHTML = text;
      chatBody.appendChild(bubble);
      chatBody.scrollTop = chatBody.scrollHeight;
    }

    async function sendPrompt() {
      const prompt = userInput.value.trim();
      if(!prompt) return;
      addBubble(prompt, true);
      userInput.value='';

      try {
        const resp = await fetch('/process_prompt', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ prompt })
        });
        const data = await resp.json();
        parseReply(data.message || data.error || 'No response.');
      } catch(err) {
        addBubble("Error connecting: "+err, false);
      }
    }

    function parseReply(reply) {
      if(reply.includes('<table') || reply.includes('slideFromRight')) {
        tablePanel.innerHTML = reply;
        addDeleteIcons();
        tablePanel.classList.add('show');
        document.getElementById('chatSection').classList.add('slideLeft');
      } else {
        addBubble(reply, false);
      }
    }

    function addDeleteIcons() {
      const table = tablePanel.querySelector('table');
      if(!table) return;
      // Add Action column if not present
      const headRow = table.querySelector('thead tr');
      if(headRow && !headRow.querySelector('.action-col')) {
        const th = document.createElement('th');
        th.textContent = 'Action';
        th.classList.add('action-col');
        headRow.appendChild(th);
      }
      const tbody = table.querySelector('tbody');
      if(!tbody) return;
      tbody.querySelectorAll('tr').forEach(tr => {
        let cells = tr.querySelectorAll('td');
        if(cells.length > 0) {
          const sid = cells[0].innerText.trim();
          const td = document.createElement('td');
          td.classList.add('action-col');
          td.innerHTML = `<button style="border:none; background:transparent; color:red;" onclick="deleteRow('${sid}')">🗑️</button>`;
          tr.appendChild(td);
        }
      });
    }

    async function deleteRow(sid) {
      try {
        const resp = await fetch('/delete_by_id', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ id: sid })
        });
        const data = await resp.json();
        if(data.success) {
          addBubble(data.message, false);
          // Re-view students
          const vresp = await fetch('/process_prompt', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ prompt: 'view students' })
          });
          const vdata = await vresp.json();
          parseReply(vdata.message);
        } else {
          addBubble("Delete error: "+(data.error || data.message), false);
        }
      } catch(err) {
        addBubble("Delete error: "+err, false);
      }
    }

    async function saveTableEdits() {
      const rows = tablePanel.querySelectorAll('table tbody tr');
      const updates = [];
      rows.forEach(r => {
        const cells = r.querySelectorAll('td');
        if(!cells.length) return;
        const sid = cells[0].innerText.trim();
        if(!sid) return;
        let name = cells[1].innerText.trim();
        let age = cells[2].innerText.trim();
        let sclass = cells[3].innerText.trim();
        let address = cells[4].innerText.trim();
        let phone = cells[5].innerText.trim();
        let guardian = cells[6].innerText.trim();
        let guardianPhone = cells[7].innerText.trim();
        let attendance = cells[8].innerText.trim();
        let grades = cells[9].innerText.trim();
        try { grades = JSON.parse(grades); } catch(e){}
        updates.push({
          id: sid,
          name,
          age,
          class: sclass,
          address,
          phone,
          guardian_name: guardian,
          guardian_phone: guardianPhone,
          attendance,
          grades
        });
      });

      try {
        const resp = await fetch('/bulk_update_students', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ updates })
        });
        const data = await resp.json();
        if(data.success) {
          addBubble("Changes saved to Firebase!", false);
        } else {
          addBubble("Error saving changes: "+(data.error || data.message), false);
        }
      } catch(err) {
        addBubble("Error saving changes: "+err, false);
      }
      tablePanel.classList.remove('show');
      document.getElementById('chatSection').classList.remove('slideLeft');
    }
  </script>
</body>
</html>
"""

###############################################################################
# 16. On Startup => Load memory, summary
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
# 17. Actually run Flask
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

    app.run(debug=True, port=8000)
    