import re
import os
import json
import random
import logging
from flask import Flask, request, jsonify, render_template

# Google Generative AI
import google.generativeai as genai

# Firebase Setup (base64 credentials)
from firebase_setup import get_firestore_client

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # For best practice, store in env var
if not GEMINI_API_KEY:
    logging.error("GEMINI_API_KEY environment variable not set.")
    raise ValueError("GEMINI_API_KEY environment variable not set.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-1.5-flash")

###############################################################################
# 4. Initialize Firestore (via firebase_setup.py)
###############################################################################
try:
    db = get_firestore_client()
    logging.info("✅ Firestore Client Initialized via firebase_setup.get_firestore_client()")
except Exception as e:
    logging.error(f"❌ Firestore client initialization error: {e}")
    raise e

###############################################################################
# 5. Conversation Memory & Activity Log
###############################################################################
conversation_memory = []
MAX_MEMORY = 20  # Adjust as needed
welcome_summary = ""

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
    try:
        db.collection('activity_log').add({
            "action_type": action_type,
            "details": details,
            "timestamp": None  # or use firestore.SERVER_TIMESTAMP if needed
        })
        logging.info(f"✅ Logged activity: {action_type}, details={details}")
    except Exception as e:
        logging.error(f"❌ Failed to log activity: {e}")

def generate_comedic_summary_of_past_activities():
    """
    Reads all logs from the 'activity_log' collection, then asks Gemini to produce
    a short dark/funny summary of them.
    """
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
            "of the following student management actions. Maintain a grim yet witty tone.\n\n"
            f"{combined}"
        )
        resp = model.generate_content(prompt)
        if resp.candidates:
            summary = resp.candidates[0].content.parts[0].text.strip()
            logging.debug(f"Comedic summary generated: {summary}")
            return summary
        else:
            return "No comedic summary could be conjured. The silence is deafening."
    except Exception as e:
        logging.error(f"❌ Error generating comedic summary: {e}")
        return "An error occurred while digging up the past activities..."

###############################################################################
# 6. Remove Triple Backticks (Code Fences)
###############################################################################
def remove_code_fences(text: str) -> str:
    fenced_pattern = r'^```(?:json)?\s*([\s\S]*?)\s*```$'
    match = re.match(fenced_pattern, text.strip())
    if match:
        return match.group(1).strip()
    return text

###############################################################################
# 7. Student Logic (Add, Update, Delete, View)
###############################################################################
def generate_student_id(name, age):
    random_number = random.randint(1000, 9999)
    name_part = (name[:4] if len(name) >= 4 else name).upper()
    age_str = str(age) if age else "00"
    return f"{name_part}{age_str}{random_number}"

def create_comedic_confirmation(action, name, student_id):
    if action == "add_student":
        prompt = (
            f"Generate a short (under 30 words), darkly funny success message confirming "
            f"the addition of {name} (ID: {student_id}). Use clear language with a touch of ominous humor."
        )
    elif action == "update_student":
        prompt = (
            f"Create a short, clear, darkly funny message confirming the update "
            f"of student ID {student_id}. Make it witty and slightly ominous."
        )
    elif action == "delete_student":
        prompt = (
            f"Create a short, clear, darkly funny message confirming the deletion "
            f"of student ID {student_id}. Make it witty and slightly ominous."
        )
    else:
        prompt = "Action completed successfully with a touch of dark humor."

    resp = model.generate_content(prompt)
    if resp.candidates:
        return truncate_response(resp.candidates[0].content.parts[0].text.strip(), max_length=100)
    else:
        return "Action completed with a hint of darkness."

def extract_fields(user_input, desired_fields):
    fields_str = ", ".join(desired_fields)
    prompt = (
        f"You are an assistant tasked with extracting specific fields from user input. "
        f"Extract the values for the following fields from the user's sentence: {fields_str}.\n"
        f"Return only a JSON object with the fields provided and their corresponding values.\n"
        f"If a field is not present, omit it.\n\n"
        f"**User Input:** '{user_input}'\n\n"
        f"**JSON Output Only:**"
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
            logging.error(f"Gemini returned invalid JSON: {content}")
            return {}
    return {}

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
            logging.error("add_student: Missing mandatory field: name")
            return {"error": "Missing mandatory field: name"}, 400

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

        log_activity("ADD_STUDENT", f"Added {name} (ID {student_id}) with data: {student_data}")

        confirmation_message = create_comedic_confirmation("add_student", name, student_id)
        return {"message": f"{confirmation_message} (ID: {student_id})"}, 200

    except Exception as e:
        logging.error(f"❌ Error in add_student: {e}")
        return {"error": str(e)}, 500

def update_student(params):
    try:
        student_id = params.get("id")
        if not student_id:
            logging.error("update_student: Missing student 'id' for update.")
            return {"error": "Missing student 'id' for update."}, 400

        update_fields = {k: v for k, v in params.items() if k != "id"}

        if not update_fields:
            logging.error("update_student: No fields provided to update.")
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
            logging.error("delete_student: Missing student 'id' for deletion.")
            return {"error": "Missing student 'id' for deletion."}, 400

        db.collection("students").document(student_id).delete()
        logging.info(f"✅ Deleted student ID {student_id} from Firestore.")

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
# 8. Flask Routes
###############################################################################
@app.route("/")
def index():
    global welcome_summary
    if not welcome_summary:
        welcome_summary = "Welcome! Here's a summary of our past activities..."
    return render_template("index.html", summary=welcome_summary)

def classify_user_input(user_prompt):
    classification_prompt = (
        "You are an intelligent assistant trained to classify user inputs into two categories: "
        "casual conversations and Firestore database actions.\n\n"
        "**Categories:**\n"
        "1. **Casual Conversation**\n"
        "   - JSON: {\"type\": \"casual\"}\n"
        "2. **Firestore Action**\n"
        "   - JSON: {\"type\": \"firestore\", \"action\": \"...\", \"parameters\": {...}}\n\n"
        "**Guidelines:**\n"
        "- If the user's input involves add, update, delete, or view of student data, return type=\"firestore\".\n"
        "- Else, return type=\"casual\".\n\n"
        f"**User Input:** '{user_prompt}'\n\n"
        "**Output:** (valid JSON only!)"
    )
    response = model.generate_content(classification_prompt)
    if response.candidates:
        content = ''.join(part.text for part in response.candidates[0].content.parts).strip()
        content = remove_code_fences(content)
        logging.debug(f"Gemini classification response: {content}")
        try:
            action_data = json.loads(content)
            if "type" not in action_data:
                raise ValueError("Missing 'type' in classification.")
            if action_data["type"] == "firestore":
                if "action" not in action_data or "parameters" not in action_data:
                    raise ValueError("Missing 'action' or 'parameters' in Firestore classification.")
            return action_data
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Invalid classification JSON: {content}. Error: {e}")
            clarification_prompt = (
                "I'm sorry, but I couldn't understand your request. Could you clarify your intent? "
                "For database operations, specify 'add/update/delete/view student.'"
            )
            clarification_response = model.generate_content(clarification_prompt)
            if clarification_response.candidates:
                clarification_message = clarification_response.candidates[0].content.parts[0].text.strip()
            else:
                clarification_message = "Could you please clarify?"
            return {"type": "clarification", "message": clarification_message}
    else:
        logging.error("No response from Gemini.")
        return {"type": "casual"}

def truncate_response(response_text, max_length=100):
    return (response_text[:max_length] + '...') if len(response_text) > max_length else response_text

@app.route("/process_prompt", methods=["POST"])
def process_prompt():
    global conversation_memory

    try:
        data = request.json
        user_prompt = data.get("prompt", "").strip()
        logging.debug(f"Received prompt: {user_prompt}")

        if not user_prompt:
            logging.warning("No prompt provided.")
            return jsonify({"error": "No prompt provided."}), 400

        # Add user input to memory
        conversation_memory.append({"role": "user", "content": user_prompt})
        if len(conversation_memory) > MAX_MEMORY:
            conversation_memory = conversation_memory[-MAX_MEMORY:]

        # Handle reset memory
        if user_prompt.lower() == "reset memory":
            conversation_memory.clear()
            save_memory_to_firestore()
            return jsonify({"message": "Memory has been reset... and so has your conscience."}), 200

        # Classify the prompt
        action_data = classify_user_input(user_prompt)
        logging.debug(f"Classification result: {action_data}")

        if action_data.get("type") == "casual":
            casual_resp = model.generate_content(user_prompt)
            if casual_resp.candidates:
                reply = casual_resp.candidates[0].content.parts[0].text.strip()
                reply = truncate_response(reply, max_length=100)
            else:
                reply = "I'm at a loss for words in this dark abyss."

            conversation_memory.append({"role": "AI", "content": reply})
            save_memory_to_firestore()
            return jsonify({"message": reply}), 200

        elif action_data.get("type") == "firestore":
            action = action_data.get("action")
            params = action_data.get("parameters", {})
            logging.debug(f"Firestore action: {action} with params {params}")

            if action == "add_student":
                desired_fields = ["name", "age", "class", "address", "phone", "guardian_name", "guardian_phone", "attendance", "grades"]
                extracted_fields = extract_fields(user_prompt, desired_fields)
                student_params = {**params, **extracted_fields}
                result, status = add_student(student_params)
                conversation_memory.append({"role": "AI", "content": result.get("message", "")})
                save_memory_to_firestore()
                return jsonify(result), status

            elif action == "update_student":
                output, status = update_student(params)
                conversation_memory.append({"role": "AI", "content": output.get("message", "")})
                save_memory_to_firestore()
                return jsonify(output), status

            elif action == "delete_student":
                output, status = delete_student(params)
                conversation_memory.append({"role": "AI", "content": output.get("message", "")})
                save_memory_to_firestore()
                return jsonify(output), status

            elif action == "view_students":
                output, status = view_students()
                conversation_memory.append({"role": "AI", "content": "Here's the list of students:"})
                conversation_memory.append({"role": "AI", "content": json.dumps(output.get("students", []), indent=2)})
                save_memory_to_firestore()
                return jsonify(output), status

            else:
                logging.warning(f"Unknown Firestore action: {action}")
                return jsonify({"error": f"Unknown Firestore action: {action}"}), 400

        elif action_data.get("type") == "clarification":
            clarification_message = action_data.get("message", "Could you please clarify your request?")
            conversation_memory.append({"role": "AI", "content": clarification_message})
            save_memory_to_firestore()
            return jsonify({"message": clarification_message}), 200

        else:
            logging.warning("Could not classify input. 'type' is missing or invalid.")
            return jsonify({"error": "Could not classify input. 'type' is missing or invalid."}), 400

    except Exception as e:
        logging.error(f"❌ An error occurred in /process_prompt: {e}")
        return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 9. Global Error Handler to Return JSON
###############################################################################
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"❌ Uncaught exception: {e}")
    return jsonify({"error": "An internal error occurred."}), 500

###############################################################################
# 10. On Startup => Generate Comedic Summary of Past Activities
###############################################################################
@app.before_first_request
def load_summary_on_startup():
    global conversation_memory
    global welcome_summary
    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info(f"🔮 Past Activities Summary: {summary}")

###############################################################################
# 11. Run Flask on Port 8000
###############################################################################
if __name__ == "__main__":
    # Load existing memory
    conversation_memory = load_memory_from_firestore()

    # Generate summary on startup
    summary = generate_comedic_summary_of_past_activities()
    welcome_summary = summary
    conversation_memory.append({"role": "system", "content": "PAST_ACTIVITIES_SUMMARY: " + summary})
    save_memory_to_firestore()
    logging.info("=== System Start Comedic Summary ===")
    logging.info(summary)
    logging.info("=====================================")

    app.run(debug=True, port=8000)
