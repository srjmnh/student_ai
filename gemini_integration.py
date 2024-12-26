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
# Switch model if needed:
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
    try:
        logs = db.collection('activity_log').order_by('timestamp').limit(100).stream()
        lines = []
        for l in logs:
            d = l.to_dict()
            lines.append(f"{d.get('action_type')}: {d.get('details')}")
        if not lines:
            return "Strangely quiet. No records... yet."

        prompt = (
            "As a grimly funny AI, summarize these student actions under 50 words:\n\n"
            + "\n".join(lines)
        )
        resp = model.generate_content(prompt)
        if resp.candidates:
            return resp.candidates[0].content.parts[0].text.strip()
        else:
            return "No comedic summary. The silence is deafening."
    except Exception as e:
        logging.error(f"❌ generate_comedic_summary error: {e}")
        return "An error occurred rummaging through the logs."

###############################################################################
# 7. Utils
###############################################################################
def remove_code_fences(t):
    import re
    pat = r'^```(?:json)?\s*([\s\S]*?)\s*```$'
    m = re.match(pat, t.strip())
    if m:
        return m.group(1).strip()
    return t

def _safe_int(v):
    if v is None:
        return None
    if isinstance(v,int):
        return v
    if isinstance(v,str) and v.isdigit():
        return int(v)
    return None

###############################################################################
# 8. Firestore Logic
###############################################################################
def delete_student_doc(doc_id):
    ref = db.collection("students").document(doc_id)
    if not ref.get().exists:
        return False,"No doc with id"
    ref.delete()
    return True,"deleted"

###############################################################################
# 9. The Basic Student Functions
###############################################################################
def add_student(params):
    import random
    name = params.get("name")
    if not name:
        return {"error":"Missing 'name'."},400
    age = _safe_int(params.get("age"))
    new_id = gen_student_id(name,age)
    doc = {
        "id": new_id,
        "name": name,
        "age": age,
        "class": params.get("class"),
        "address": params.get("address"),
        "phone": params.get("phone"),
        "guardian_name": params.get("guardian_name"),
        "guardian_phone": params.get("guardian_phone"),
        "attendance": params.get("attendance"),
        "grades": params.get("grades") or {},
        "grades_history":[]
    }
    db.collection("students").document(new_id).set(doc)
    log_activity("ADD_STUDENT", f"Added {name} => {new_id}")
    conf = comedic_confirmation("add_student", name, new_id)
    return {"message":f"{conf} (ID: {new_id})"},200

def gen_student_id(name,age):
    import random
    r = random.randint(1000,9999)
    part = (name[:4].upper() if len(name)>=4 else name.upper())
    a = str(age) if age else "00"
    return f"{part}{a}{r}"

def comedic_confirmation(action, name=None, doc_id=None):
    if action=="add_student":
        pr= f"Generate a short, darkly funny success confirming new student {name} ID {doc_id}."
    elif action=="delete_student":
        pr= f"Create a short, darkly witty message confirming the deletion of ID {doc_id}."
    else:
        pr="A cryptic success message."
    r= model.generate_content(pr)
    if r.candidates:
        return r.candidates[0].content.parts[0].text.strip()[:100]
    else:
        return "Action done."

def update_student(params):
    sid= params.get("id")
    if not sid:
        return {"error":"Missing 'id'."},400
    ref= db.collection("students").document(sid)
    sn= ref.get()
    if not sn.exists:
        return {"error":f"No doc {sid} found."},404
    upd={}
    for k,v in params.items():
        if k=="id": continue
        if k=="grades":
            old_g= sn.to_dict().get("grades",{})
            h= sn.to_dict().get("grades_history",[])
            h.append({"old":old_g,"new":v})
            upd["grades_history"]=h
        upd[k]=v
    ref.update(upd)
    log_activity("UPDATE_STUDENT",f"Updated {sid} => {upd}")
    c= comedic_confirmation("update_student", doc_id=sid)
    return {"message":c},200

def analytics_student(params):
    sid= params.get("id")
    if not sid:
        return {"error":"Missing 'id'."},400
    ref= db.collection("students").document(sid)
    sn= ref.get()
    if not sn.exists:
        return {"error":f"No doc {sid} found."},404
    data= sn.to_dict()
    hist= data.get("grades_history",[])
    if not hist:
        return {"message":f"No historical grades for {data['name']}."},200
    # simplistic approach
    return {"message":"(Analytics not fully implemented.)"},200

###############################################################################
# 10. The main classification 
###############################################################################
def classify_casual_or_firestore(prompt):
    classification_prompt = (
        "You are an advanced assistant that decides if the user prompt is casual or a Firestore operation.\n"
        "If casual => {\"type\":\"casual\"}\n"
        "If firestore => {\"type\":\"firestore\",\"action\":\"...\",\"parameters\":{...}}\n"
        "Allowed actions: add_student, update_student, delete_student, view_students, cleanup_data, analytics_student.\n"
        f"User Prompt:'{prompt}'\n"
        "Output JSON only."
    )
    r= model.generate_content(classification_prompt)
    if not r.candidates:
        return {"type":"casual"}
    raw= r.candidates[0].content.parts[0].text.strip()
    raw= remove_code_fences(raw)
    import json
    try:
        d= json.loads(raw)
        if "type" not in d:
            d["type"]="casual"
        return d
    except:
        return {"type":"casual"}

###############################################################################
# 11. Deletion logic if no ID
###############################################################################
def search_students_by_name(name):
    docs= db.collection("students").where("name","==",name).stream()
    results=[]
    for d in docs:
        st= d.to_dict()
        st_id = d.id
        st["id"]=st_id
        results.append(st)
    return results

def interpret_delete_choice(user_input, candidates):
    """
    user might say "first" => candidates[0].id
                 "second" => candidates[1].id
                 or an actual ID
    """
    txt= user_input.strip().lower()
    if txt in ["first","1","one"]:
        if len(candidates)>0:
            return candidates[0]["id"]
    elif txt in ["second","2","two"]:
        if len(candidates)>1:
            return candidates[1]["id"]
    # or might be an ID
    for c in candidates:
        if txt in [c["id"].lower(), c["id"]]: 
            return c["id"]
    return None

###############################################################################
# 12. State Machine
###############################################################################
def handle_state_machine(user_prompt):
    st= conversation_context["state"]
    pend= conversation_context["pending_params"]
    delete_candidates= conversation_context.get("delete_candidates",[])

    if st== STATE_AWAITING_DELETE_CHOICE:
        # interpret the user input (first, second, or an ID)
        chosen_id= interpret_delete_choice(user_prompt, delete_candidates)
        conversation_context["state"]= STATE_IDLE
        conversation_context["delete_candidates"]=[]
        if not chosen_id:
            return "I couldn't interpret your choice. (Try 'first', 'second', or a known ID.)"
        # do the delete
        ok, msg= delete_student_doc(chosen_id)
        if not ok:
            return f"Error: {msg}"
        # log
        log_activity("DELETE_STUDENT", f"Deleted {chosen_id}")
        conf= comedic_confirmation("delete_student", doc_id=chosen_id)
        return conf

    # normal logic
    c= classify_casual_or_firestore(user_prompt)
    if c["type"]=="casual":
        rr= model.generate_content(user_prompt)
        if rr.candidates:
            return rr.candidates[0].content.parts[0].text.strip()
        else:
            return "I'm out of words..."

    elif c["type"]=="firestore":
        a= c.get("action")
        params= c.get("parameters",{})
        if a=="delete_student":
            # if user gave ID => direct
            sid= params.get("id")
            if sid:
                ok,msg= delete_student_doc(sid)
                if not ok:
                    return "No doc with that ID found."
                log_activity("DELETE_STUDENT", f"Deleted {sid}")
                conf= comedic_confirmation("delete_student", doc_id=sid)
                return conf
            # else no ID => check if name
            name= params.get("name")
            if not name:
                return "We need an ID or a name to delete."
            # search
            matches= search_students_by_name(name)
            if not matches:
                return f"No student named {name} found."
            if len(matches)==1:
                # delete directly
                found_id= matches[0]["id"]
                ok,msg= delete_student_doc(found_id)
                if not ok:
                    return "No doc with that ID found."
                log_activity("DELETE_STUDENT", f"Deleted {found_id}")
                conf= comedic_confirmation("delete_student", doc_id=found_id)
                return conf
            else:
                # multiple => store in context
                conversation_context["state"]= STATE_AWAITING_DELETE_CHOICE
                conversation_context["delete_candidates"]= matches
                # show them
                lines=[]
                for i,m in enumerate(matches):
                    lines.append(f"{i+1}. ID={m['id']} | Class={m.get('class','')} | Age={m.get('age','')}")
                listing= "\n".join(lines)
                return f"Multiple matches for {name}:\n{listing}\nWhich one do you want to delete? (Say 'first', 'second', or the actual ID.)"

        elif a=="view_students":
            return build_students_table_html("Student Records")

        elif a=="cleanup_data":
            return cleanup_data()

        elif a=="add_student":
            return handle_add_student(params)

        elif a=="update_student":
            return handle_update_student(params)

        elif a=="analytics_student":
            return handle_analytics(params)

        else:
            return f"Unknown Firestore action: {a}"
    else:
        # fallback
        return "I'm not sure what you're asking."

def handle_add_student(p):
    # if missing name => partial
    n= p.get("name")
    if not n:
        conversation_context["state"]= STATE_AWAITING_STUDENT_INFO
        conversation_context["pending_params"]= p
        conversation_context["last_intended_action"]= "add_student"
        return "Let's add a new student. What's their name?"
    else:
        out, sts= add_student(p)
        if sts==200 and "message" in out:
            # comedic follow
            fp= create_funny_prompt_for_new_student(p["name"])
            r2= model.generate_content(fp)
            if r2.candidates:
                t= r2.candidates[0].content.parts[0].text.strip()
                return out["message"]+"\n\n"+t
            else:
                return out["message"]
        else:
            return out.get("error","Error adding student.")

def handle_update_student(p):
    out, st= update_student(p)
    return out.get("message", out.get("error","Error."))

def handle_analytics(p):
    sid= p.get("id")
    name= p.get("name")
    if not (sid or name):
        # partial
        conversation_context["state"]= STATE_AWAITING_ANALYTICS_TARGET
        conversation_context["pending_params"]= p
        conversation_context["last_intended_action"]= "analytics_student"
        return "Which student do you want to check? Provide ID or name."
    else:
        return do_analytics_student(p)

def do_analytics_student(p):
    out, st= analytics_student(p)
    return out.get("message", out.get("error","Error."))

###############################################################################
# 13. Actually delete from doc_id route for the trash icon
###############################################################################
@app.route("/delete_by_id", methods=["POST"])
def delete_by_id():
    data= request.json
    sid= data.get("id")
    if not sid:
        return jsonify({"error":"No ID."}),400
    ok,msg= delete_student_doc(sid)
    if not ok:
        return jsonify({"error":"No doc with that ID found."}),404
    log_activity("DELETE_STUDENT", f"Deleted {sid} via icon.")
    conf= comedic_confirmation("delete_student", doc_id=sid)
    return jsonify({"success":True,"message":conf}),200

###############################################################################
# 14. Flask HTML: Dark Mode + Intro Page + Table Icons
###############################################################################
@app.route("/")
def index():
    global welcome_summary
    # Provide the comedic summary as we do a separate 'intro' screen
    safe_sum= welcome_summary.replace('"','\\"').replace('\n','\\n')
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
      text-align:center; padding:2rem;
      z-index:9999; /* ensure on top */
      transition: opacity 0.5s ease;
    }}
    #introScreen.hidden {{
      opacity:0; pointer-events:none;
    }}
    .chat-wrap {{
      max-width:700px; margin:2rem auto; background:#fff; 
      border-radius:0.5rem; box-shadow:0 4px 10px rgba(0,0,0,0.1);
      display:flex; flex-direction:column; height:80vh; overflow:hidden;
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
    <h1 style="font-size:1.5rem; max-width:600px;">
      “{safe_sum}”
    </h1>
    <button class="btn btn-light" onclick="hideIntro()">Continue</button>
  </div>

  <!-- Background music with random track from an array of URLs -->
  <audio id="bgMusic" autoplay loop></audio>

  <div class="chat-wrap" id="chatSection" style="display:none;">
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
    // 1) Intro screen logic
    function hideIntro() {
      const intro = document.getElementById('introScreen');
      intro.classList.add('hidden');
      setTimeout(() => {
        intro.style.display='none';
        document.getElementById('chatSection').style.display='';
      }, 500);
    }

    // 2) Dark mode toggle
    function toggleDarkMode() {
      document.body.classList.toggle('dark-mode');
    }

    // 3) Random music
    const musicTracks = [
      "https://www.bensound.com/bensound-music/bensound-anewbeginning.mp3",
      "https://www.bensound.com/bensound-music/bensound-ukulele.mp3",
      "https://www.bensound.com/bensound-music/bensound-funnysong.mp3"
    ];

    window.addEventListener('DOMContentLoaded', () => {
      const bgMusic = document.getElementById('bgMusic');
      const randomUrl = musicTracks[Math.floor(Math.random() * musicTracks.length)];
      bgMusic.src = randomUrl;
    });

    // 4) Chat + Table logic
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
        parseReply(data.message || data.error || 'No response.');
      } catch(err) {
        addBubble("Error connecting: "+err,false);
      }
    }

    function parseReply(reply) {
      if(reply.includes('<table') || reply.includes('slideFromRight')) {
        tablePanel.innerHTML= reply;
        // Add a delete icon in each row?
        // Let's do that after the table is loaded:
        addDeleteIcons();

        tablePanel.classList.add('show');
        chatSection.classList.add('slideLeft');
      } else {
        addBubble(reply,false);
      }
    }

    function addDeleteIcons() {
      const table = tablePanel.querySelector('table');
      if(!table) return;
      // Insert an Action column if not present
      const thead = table.querySelector('thead tr');
      if(thead && !thead.querySelector('.delete-col')) {
        const th = document.createElement('th');
        th.className='delete-col';
        th.textContent='Action';
        thead.appendChild(th);
      }
      const tbody = table.querySelector('tbody');
      if(!tbody) return;
      tbody.querySelectorAll('tr').forEach(tr => {
        let tds = tr.querySelectorAll('td');
        if(tds.length > 0) {
          // Add a last TD with a trash icon
          const td = document.createElement('td');
          td.className='delete-col';
          const sid= tds[0].innerText.trim(); // doc ID is in first cell
          td.innerHTML= `<button style="border:none; background:transparent; color:red;" onclick="deleteRow('${sid}')">🗑️</button>`;
          tr.appendChild(td);
        }
      });
    }

    async function deleteRow(sid) {
      // direct call to /delete_by_id
      try {
        const res= await fetch('/delete_by_id',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ id:sid })
        });
        const data= await res.json();
        if(data.success) {
          // refresh table
          addBubble(data.message,false);
          // let's re-view students
          const viewResp= await fetch('/process_prompt',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ prompt:'view students' })
          });
          const viewData= await viewResp.json();
          parseReply(viewData.message);
        } else {
          addBubble("Delete error: "+(data.error||data.message),false);
        }
      } catch(err) {
        addBubble("Delete error: "+err,false);
      }
    }

    async function saveTableEdits() {
      const rows= tablePanel.querySelectorAll('table tbody tr');
      const updates= [];
      rows.forEach(r => {
        const cells= r.querySelectorAll('td');
        if(!cells.length) return;
        const sid= cells[0].innerText.trim();
        if(!sid) return;

        let name= cells[1].innerText.trim();
        let age= cells[2].innerText.trim();
        let sclass= cells[3].innerText.trim();
        let address= cells[4].innerText.trim();
        let phone= cells[5].innerText.trim();
        let guardian= cells[6].innerText.trim();
        let guardianPhone= cells[7].innerText.trim();
        let attendance= cells[8].innerText.trim();
        let grades= cells[9].innerText.trim();
        try { grades= JSON.parse(grades); } catch(e){}
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
        const resp= await fetch('/bulk_update_students',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ updates })
        });
        const data= await resp.json();
        if(data.success) {
          addBubble("Changes saved to Firebase!",false);
        } else {
          addBubble("Error saving changes: "+(data.error||data.message),false);
        }
      } catch(err) {
        addBubble("Error saving changes: "+err,false);
      }
      tablePanel.classList.remove('show');
      chatSection.classList.remove('slideLeft');
    }
  </script>
</body>
</html>
"""

###############################################################################
# 15. Delete by ID route for the table trash icon
###############################################################################
@app.route("/delete_by_id", methods=["POST"])
def delete_by_id():
    data= request.json
    sid= data.get("id")
    if not sid:
        return jsonify({"error":"No ID"}),400
    ref= db.collection("students").document(sid)
    if not ref.get().exists:
        return jsonify({"error":"No doc with that ID found."}),404
    ref.delete()
    log_activity("DELETE_STUDENT", f"Deleted {sid} via trash icon.")
    cc= comedic_confirmation("delete_student", doc_id=sid)
    return jsonify({"success":True,"message":cc}),200

###############################################################################
# 16. Bulk Update
###############################################################################
@app.route("/bulk_update_students", methods=["POST"])
def bulk_update_students_route():
    data= request.json
    updates= data.get("updates",[])
    if not updates:
        return jsonify({"error":"No updates provided."}),400
    updated= bulk_update_students(updates)
    return jsonify({"success":True, "updated_ids":updated}),200

###############################################################################
# 17. The main route to handle user prompts
###############################################################################
@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    global conversation_memory, conversation_context
    req= request.json
    user_prompt= req.get("prompt","").strip()
    if not user_prompt:
        return jsonify({"error":"No prompt"}),400

    # store user
    conversation_memory.append({"role":"user","content": user_prompt})
    if len(conversation_memory)>MAX_MEMORY:
        conversation_memory= conversation_memory[-MAX_MEMORY:]

    # reset memory
    if user_prompt.lower() in ["reset memory","reset conversation","cancel"]:
        conversation_memory.clear()
        conversation_context["state"]= STATE_IDLE
        conversation_context["pending_params"]={}
        conversation_context["last_intended_action"]=None
        conversation_context["delete_candidates"]=[]
        save_memory_to_firestore()
        return jsonify({"message":"Memory & context reset."}),200

    reply= handle_state_machine(user_prompt)
    # store AI
    conversation_memory.append({"role":"AI","content": reply})
    save_memory_to_firestore()
    return jsonify({"message":reply}),200

###############################################################################
# 18. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exc(e):
    logging.error(f"Uncaught Exception: {e}")
    return jsonify({"error":"An internal error occurred."}),500

###############################################################################
# 19. Startup => load memory + comedic summary
###############################################################################
@app.before_first_request
def load_on_start():
    global conversation_memory, conversation_context, welcome_summary
    mem, ctx= load_memory_from_firestore()
    if mem:
        conversation_memory.extend(mem)
    if ctx:
        conversation_context.update(ctx)
    # generate comedic summary
    sumy= generate_comedic_summary_of_past_activities()
    welcome_summary= sumy
    conversation_memory.append({"role":"system","content":"PAST_ACTIVITIES_SUMMARY: "+sumy})
    save_memory_to_firestore()
    logging.info("Startup summary: "+sumy)

###############################################################################
# 20. Run
###############################################################################
if __name__=="__main__":
    mem,ctx= load_memory_from_firestore()
    if mem: conversation_memory.extend(mem)
    if ctx: conversation_context.update(ctx)
    sumy= generate_comedic_summary_of_past_activities()
    welcome_summary= sumy
    conversation_memory.append({"role":"system","content":"PAST_ACTIVITIES_SUMMARY: "+sumy})
    save_memory_to_firestore()

    app.run(debug=True,port=8000)