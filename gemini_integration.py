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
app = Flask(__name__, static_folder='static')

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
    logging.error("GEMINI_API_KEY environment variable not set.")
    raise ValueError("GEMINI_API_KEY environment variable not set.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-1.5-flash")  
# If you don't have access to Gemini, try: "models/chat-bison-001"

###############################################################################
# 4. Firebase Initialization
#    (Using base64-encoded credentials from FIREBASE_CREDENTIALS)
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
# 5. Conversation + State Machine + Activity Log
###############################################################################
# We'll store a minimal "state machine" in memory. For multi-user concurrency,
# you'd store it in Firestore keyed by user/session ID. This is a single-user demo.
###############################################################################

# Possible conversation states
STATE_IDLE = "IDLE"
STATE_AWAITING_STUDENT_INFO = "AWAITING_STUDENT_INFO"
STATE_AWAITING_STUDENT_SELECTION = "AWAITING_STUDENT_SELECTION"

# We'll keep a global dictionary to track conversation context, including current state.
conversation_context = {
    "state": STATE_IDLE,
    # We'll store partial user parameters, e.g. name, class, address, etc.
    "pending_params": {},
    # If searching for students by name yields multiple matches, store them here
    "possible_students": [],
    # We'll also keep the last intended action ("add_student", "delete_student", etc.)
    "intended_action": None
}

# We'll still maintain conversation memory for summarization or debugging
conversation_memory = []
MAX_MEMORY = 20
welcome_summary = ""

def save_memory_to_firestore():
    try:
        db.collection('conversation_memory').document('session_1').set({
            "memory": conversation_memory,
            "context": conversation_context  # Save context as well
        })
        logging.info("✅ Memory and context saved to Firestore.")
    except Exception as e:
        logging.error(f"❌ Failed to save memory: {e}")

def load_memory_from_firestore():
    try:
        doc = db.collection('conversation_memory').document('session_1').get()
        if doc.exists:
            data = doc.to_dict()
            logging.info("✅ Loaded conversation memory from Firestore.")
            return data.get("memory", []), data.get("context", {})
        logging.info("✅ No existing conversation memory found.")
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
            logging.debug(f"Comedic summary generated: {summary}")
            return summary
        else:
            return "No comedic summary conjured. The silence is deafening."
    except Exception as e:
        logging.error(f"❌ Error generating comedic summary: {e}")
        return "An error occurred while digging up the past activities..."

###############################################################################
# 6. Remove Triple Backticks Helper
###############################################################################
def remove_code_fences(text: str) -> str:
    fenced_pattern = r'^```(?:json)?\s*([\s\S]*?)\s*```$'
    match = re.match(fenced_pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text

###############################################################################
# 7. Firestore Helper Functions
###############################################################################
def find_students_by_name(name):
    """
    Return a list of all students that match the provided name (case-insensitive).
    You could make this fuzzy, but here's a simple approach.
    """
    docs = db.collection("students").where("name", "==", name).stream()
    return [doc.to_dict() for doc in docs]

def generate_student_id(name, age):
    random_number = random.randint(1000, 9999)
    name_part = (name[:4] if len(name) >= 4 else name).upper()
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def create_comedic_confirmation(action, name, student_id):
    if action == "add_student":
        prompt = (
            f"Generate a short, darkly funny success message confirming the addition "
            f"of {name} (ID: {student_id})."
        )
    elif action == "update_student":
        prompt = (
            f"Create a short, darkly funny message confirming the update "
            f"of student ID {student_id}."
        )
    elif action == "delete_student":
        prompt = (
            f"Create a short, darkly funny message confirming the deletion "
            f"of student ID {student_id}."
        )
    else:
        prompt = "Action completed with a hint of darkness."

    resp = model.generate_content(prompt)
    if resp.candidates:
        text_resp = resp.candidates[0].content.parts[0].text.strip()
        return text_resp[:100]  # Truncate to 100 chars if too long
    else:
        return "Action completed with a hint of darkness."

def add_student(params):
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
            return {"error": "Missing 'name' to add student."}, 400

        student_id = generate_student_id(name, age)
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

        db.collection("students").document(student_id).set(student_data)
        logging.info(f"✅ Added student to Firestore: {student_data}")

        log_activity("ADD_STUDENT", f"Added {name} (ID {student_id}).")

        confirmation_message = create_comedic_confirmation("add_student", name, student_id)
        return {"message": f"{confirmation_message} (ID: {student_id})"}, 200

    except Exception as e:
        logging.error(f"❌ Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing student 'id' for update."}, 400

        update_fields = {k: v for k, v in params.items() if k != "id"}
        if not update_fields:
            return {"error": "No fields provided to update."}, 400

        db.collection("students").document(student_id).update(update_fields)
        logging.info(f"✅ Updated student {student_id} with {update_fields}")

        log_activity("UPDATE_STUDENT", f"Updated {student_id} with {update_fields}")

        confirmation_message = create_comedic_confirmation("update_student", None, student_id)
        return {"message": confirmation_message}, 200

    except Exception as e:
        logging.error(f"❌ Error in update_student: {e}")
        return {"error": str(e)}, 500

def delete_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            return {"error": "Missing student 'id' for deletion."}, 400

        db.collection("students").document(student_id).delete()
        logging.info(f"✅ Deleted student ID {student_id}")

        log_activity("DELETE_STUDENT", f"Deleted student ID {student_id}")

        confirmation_message = create_comedic_confirmation("delete_student", None, student_id)
        return {"message": confirmation_message}, 200

    except Exception as e:
        logging.error(f"❌ Error in delete_student: {e}")
        return {"error": str(e)}, 500

def view_students():
    try:
        docs = db.collection("students").stream()
        student_list = [doc.to_dict() for doc in docs]

        log_activity("VIEW_STUDENTS", f"Viewed all {len(student_list)} students.")

        return {"students": student_list}, 200

    except Exception as e:
        logging.error(f"❌ Error in view_students: {e}")
        return {"error": str(e)}, 500

###############################################################################
# 8. Classification Prompt
#    We'll ask Gemini to figure out if user wants to:
#    - add_student
#    - update_student
#    - delete_student
#    - view_students
#    or it's partial, or is a casual conversation
###############################################################################
def classify_user_input(user_prompt):
    classification_prompt = (
        "You are an advanced assistant that classifies user input into Firestore actions or casual talk.\n\n"
        "**Actions**:\n"
        " - add_student\n"
        " - update_student\n"
        " - delete_student\n"
        " - view_students\n\n"
        "The user might say partial phrases like 'Add new pupil' or 'Show me all students' or 'Remove John.'\n"
        "Return valid JSON only, no extra text.\n\n"
        "If user wants to add, update, delete, or view students, return:\n"
        "{\n"
        "  \"type\": \"firestore\", \n"
        "  \"action\": \"add_student\" (or other), \n"
        "  \"parameters\": { ... }\n"
        "}\n\n"
        "If the user is casually talking or something else, return:\n"
        "{ \"type\": \"casual\" }\n\n"
        "Try to extract partial parameters from the user input (e.g. name, class, phone) if present.\n"
        "For partial or uncertain data, just fill what you can in 'parameters'.\n\n"
        f"User Input: '{user_prompt}'\n\n"
        "Output (JSON only):"
    )

    response = model.generate_content(classification_prompt)
    if not response.candidates:
        logging.error("No response from Gemini classification.")
        return {"type": "casual"}

    content = ''.join(part.text for part in response.candidates[0].content.parts).strip()
    content = remove_code_fences(content)
    logging.debug(f"Gemini classification response: {content}")

    try:
        action_data = json.loads(content)
        if "type" not in action_data:
            raise ValueError("Missing 'type'.")
        if action_data["type"] == "firestore":
            if "action" not in action_data or "parameters" not in action_data:
                raise ValueError("Firestore JSON must have 'action' and 'parameters'.")

            # Normalize known short actions (like "add" => "add_student") if needed
            short_map = {
                "add": "add_student",
                "update": "update_student",
                "delete": "delete_student",
                "view": "view_students"
            }
            raw_action = action_data["action"].lower().strip()
            if raw_action in short_map:
                action_data["action"] = short_map[raw_action]

        return action_data

    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Invalid classification JSON: {content}. Error: {e}")
        return {"type": "casual"}

###############################################################################
# 9. State Machine Logic
#    We'll define a function that checks the current context/state and decides
#    what to do next.
###############################################################################
def handle_state_machine(user_prompt):
    """
    High-level logic that uses conversation_context to decide what to do.
    1) If state=AWAITING_STUDENT_INFO, we might parse missing fields from the user prompt.
    2) If state=AWAITING_STUDENT_SELECTION, we might see which student the user wants from a list.
    3) Otherwise, we classify normally and handle actions.
    """
    state = conversation_context["state"]
    logging.debug(f"Current state: {state}")

    # 1) If we're waiting for student info to complete an 'add_student'
    if state == STATE_AWAITING_STUDENT_INFO:
        # Try to parse new data from user input
        # We'll define the "desired_fields" for an add operation, for example.
        desired_fields = ["name", "age", "class", "address", "phone", "guardian_name", "guardian_phone"]
        extracted = extract_fields(user_prompt, desired_fields)

        # Merge into pending_params
        for k, v in extracted.items():
            conversation_context["pending_params"][k] = v

        # Check if we have the minimal required: 'name'
        if not conversation_context["pending_params"].get("name"):
            return "I still need the student's name. Please provide it."

        # We can proceed to add now or ask for more. Let's add if we have a name.
        # If you want to ask for missing optional fields (phone, address, etc.), you could prompt again.
        result, status = add_student(conversation_context["pending_params"])
        conversation_context["pending_params"] = {}  # Clear
        conversation_context["state"] = STATE_IDLE
        conversation_context["intended_action"] = None
        return result.get("message", result.get("error", "Done."))

    # 2) If we're waiting for student selection (e.g. multiple John found)
    if state == STATE_AWAITING_STUDENT_SELECTION:
        # The user might specify which student ID to delete or update
        # We'll parse the user prompt to see if there's an ID
        # For simplicity, let's see if user typed something like 'delete ABCD1234'
        # But let's do a quick search for an ID in the user_prompt
        words = user_prompt.split()
        chosen_id = None
        for w in words:
            if len(w) >= 5 and w.isalnum():
                chosen_id = w
                break

        if not chosen_id:
            return "Please specify the exact student ID from the list above."

        # We'll see what the intended_action was. e.g. "delete_student"
        intended = conversation_context["intended_action"]
        if intended == "delete_student":
            output, status = delete_student({"id": chosen_id})
            # Clear possible_students, reset state
            conversation_context["possible_students"] = []
            conversation_context["state"] = STATE_IDLE
            conversation_context["intended_action"] = None
            return output.get("message", output.get("error", "Delete done."))

        elif intended == "update_student":
            # This is more complex, we'd ask which fields to update, etc.
            # For brevity, let's do a direct partial approach:
            conversation_context["pending_params"]["id"] = chosen_id
            output, status = update_student(conversation_context["pending_params"])
            conversation_context["possible_students"] = []
            conversation_context["pending_params"] = {}
            conversation_context["state"] = STATE_IDLE
            conversation_context["intended_action"] = None
            return output.get("message", output.get("error", "Update done."))

        else:
            # If the user was asked to pick a student for something else,
            # handle it similarly.
            conversation_context["state"] = STATE_IDLE
            return f"Not sure what to do with ID {chosen_id}. State reset."

    # 3) If state=IDLE or otherwise, we classify
    action_data = classify_user_input(user_prompt)
    if action_data.get("type") == "casual":
        # Just respond casually
        casual_resp = model.generate_content(user_prompt)
        if casual_resp.candidates:
            return casual_resp.candidates[0].content.parts[0].text.strip()
        else:
            return "I'm at a loss for words..."

    elif action_data.get("type") == "firestore":
        action = action_data["action"]
        params = action_data["parameters"]

        if action == "view_students":
            # Show the list
            output, status = view_students()
            if "students" in output:
                # Return them in text form
                return "Here are the students:\n" + json.dumps(output["students"], indent=2)
            else:
                return output.get("error", "Something went wrong with view_students")

        elif action == "add_student":
            # If minimal param 'name' is missing, ask for it
            if not params.get("name"):
                # Switch to waiting state
                conversation_context["state"] = STATE_AWAITING_STUDENT_INFO
                conversation_context["pending_params"] = params
                conversation_context["intended_action"] = "add_student"
                return "Alright, let's add a new student. What's the student's name?"

            # If we have a name, let's add right away
            result, status = add_student(params)
            return result.get("message", result.get("error", "Add student error."))

        elif action == "delete_student":
            # If user gave an ID, just delete
            if params.get("id"):
                result, status = delete_student(params)
                return result.get("message", result.get("error", "Delete error."))
            # If user gave a name, find matches
            elif params.get("name"):
                matches = find_students_by_name(params["name"])
                if not matches:
                    return f"No student found with name {params['name']}."
                if len(matches) == 1:
                    # We can delete directly
                    student_id = matches[0]["id"]
                    result, status = delete_student({"id": student_id})
                    return result.get("message", result.get("error", "Delete error."))
                else:
                    # Multiple matches => ask user which ID
                    conversation_context["possible_students"] = matches
                    conversation_context["state"] = STATE_AWAITING_STUDENT_SELECTION
                    conversation_context["intended_action"] = "delete_student"
                    # Display them
                    listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
                    return f"Multiple students named {params['name']} found:\n{listing}\nWhich ID do you want to delete?"
            else:
                return "Who do you want to delete? Provide a name or ID."

        elif action == "update_student":
            # This could be more sophisticated if the user says "update John" 
            # and we find multiple or none. For brevity, let's handle ID or name:
            if params.get("id"):
                # If ID, we can update right away
                result, status = update_student(params)
                return result.get("message", result.get("error", "Update error."))
            elif params.get("name"):
                matches = find_students_by_name(params["name"])
                if not matches:
                    return f"No student found with name {params['name']}."
                if len(matches) == 1:
                    # Only one match, let's update. Add 'id' to params
                    params["id"] = matches[0]["id"]
                    result, status = update_student(params)
                    return result.get("message", result.get("error", "Update error."))
                else:
                    conversation_context["possible_students"] = matches
                    conversation_context["pending_params"] = params
                    conversation_context["state"] = STATE_AWAITING_STUDENT_SELECTION
                    conversation_context["intended_action"] = "update_student"
                    listing = "\n".join([f"{m['id']}: {m['name']}" for m in matches])
                    return f"Multiple matches found for '{params['name']}':\n{listing}\nWhich ID do you want to update?"
            else:
                return "Please specify which student to update (by 'id' or 'name')."

        else:
            return f"Unknown firestore action: {action}"

    else:
        # Type is something else or incomplete
        return "I'm not sure I understood. Could you clarify what you want?"

###############################################################################
# 10. Helper for extracting fields from user input (for partial)
###############################################################################
def extract_fields(user_input, desired_fields):
    fields_str = ", ".join(desired_fields)
    prompt = (
        f"You are an assistant that extracts specific fields from user input. "
        f"Fields: {fields_str}. Return JSON with only those fields if present.\n\n"
        f"User Input: '{user_input}'\n\n"
        "Output (JSON only):"
    )
    resp = model.generate_content(prompt)
    if resp.candidates:
        content = ''.join(part.text for part in resp.candidates[0].content.parts).strip()
        content = remove_code_fences(content)
        logging.debug(f"Gemini extraction response: {content}")
        try:
            extracted = json.loads(content)
            logging.debug(f"Extracted fields: {extracted}")
            return extracted
        except json.JSONDecodeError:
            logging.error(f"Gemini returned invalid JSON for extraction: {content}")
            return {}
    return {}

###############################################################################
# 11. Flask Routes
###############################################################################
@app.route("/")
def index():
    global welcome_summary
    if not welcome_summary:
        welcome_summary = "Welcome! Here's a summary of our past activities..."
    # You can render an HTML file that calls "/process_prompt" via AJAX or fetch
    return render_template("index.html", summary=welcome_summary)

@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    global conversation_memory, conversation_context

    data = request.json
    user_prompt = data.get("prompt", "").strip()
    logging.debug(f"Received prompt: {user_prompt}")

    if not user_prompt:
        return jsonify({"message": "No prompt provided."}), 400

    # Append to conversation memory
    conversation_memory.append({"role": "user", "content": user_prompt})
    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory = conversation_memory[-MAX_MEMORY:]

    # If user says 'reset memory'
    if user_prompt.lower() in ["reset memory", "reset conversation"]:
        conversation_memory.clear()
        # Reset context
        conversation_context["state"] = STATE_IDLE
        conversation_context["pending_params"] = {}
        conversation_context["possible_students"] = []
        conversation_context["intended_action"] = None
        save_memory_to_firestore()
        return jsonify({"message": "Memory and context reset."}), 200

    # Let the state machine handle it
    system_reply = handle_state_machine(user_prompt)

    # Append AI's reply
    conversation_memory.append({"role": "AI", "content": system_reply})
    save_memory_to_firestore()

    return jsonify({"message": system_reply}), 200

###############################################################################
# 12. Global Error Handler
###############################################################################
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"❌ Uncaught exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 13. On Startup => Generate Comedic Summary
###############################################################################
@app.before_first_request
def load_summary_on_startup():
    global conversation_memory, conversation_context, welcome_summary
    # Attempt to load memory and context
    memory, ctx = load_memory_from_firestore()
    if memory:
        conversation_memory.extend(memory)
    if ctx:
        conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info(f"🔮 Past Activities Summary: {summary}")

###############################################################################
# 14. Run Flask on Port 8000
###############################################################################
if __name__ == "__main__":
    # Load existing memory/context if any
    memory, ctx = load_memory_from_firestore()
    conversation_memory = memory if memory else conversation_memory
    if ctx:
        conversation_context.update(ctx)

    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info("=== System Start Comedic Summary ===")
    logging.info(summary)
    logging.info("=====================================")

    app.run(debug=True, port=8000)
