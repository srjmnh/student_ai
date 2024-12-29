from flask import jsonify, request, current_app
from app.blueprints.hr import hr_bp
from app.firestore_client import get_firestore_client
from app.gemini_integration import GeminiIntegration
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth
from google.cloud import firestore

def token_required(f):
    from functools import wraps
    def decorator(*args, **kwargs):
        from flask import request
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'error': 'Token is missing.'}), 401
        try:
            decoded_token = firebase_auth.verify_id_token(token)
            uid = decoded_token['uid']
            db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
            user_doc = db.collection('users').document(uid).get()
            if not user_doc.exists:
                return jsonify({'error': 'User does not exist.'}), 404
            user_data = user_doc.to_dict()
            if user_data.get('role') != 'hr':
                return jsonify({'error': 'Unauthorized access.'}), 403
            # Attach user info to the request context if needed
            request.user = {
                'uid': uid,
                'email': user_data.get('email'),
                'role': user_data.get('role')
            }
        except firebase_admin.auth.InvalidIdTokenError:
            logging.warning("Invalid Firebase ID Token.")
            return jsonify({'error': 'Invalid token.'}), 401
        except firebase_admin.auth.ExpiredIdTokenError:
            logging.warning("Expired Firebase ID Token.")
            return jsonify({'error': 'Token expired.'}), 401
        except Exception as e:
            logging.error(f"Token verification failed: {e}")
            return jsonify({'error': 'Token verification failed.'}), 500
        return f(*args, **kwargs)
    return wraps(f)(decorator)

@hr_bp.route('/dashboard', methods=['GET'])
@token_required
def dashboard():
    db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
    # Fetch all employees
    employees = db.collection('employees').stream()
    employee_list = [emp.to_dict() for emp in employees]
    return jsonify({'employees': employee_list}), 200

@hr_bp.route('/add_employee', methods=['POST'])
@token_required
def add_employee():
    """
    Endpoint to add a new employee.
    Expects JSON payload with 'emp_id', 'name', 'position', 'department', 'email', 'phone'.
    """
    data = request.json
    emp_id = data.get('emp_id')
    name = data.get('name')
    position = data.get('position')
    department = data.get('department')
    email = data.get('email')
    phone = data.get('phone')
    
    if not all([emp_id, name, position, department, email, phone]):
        return jsonify({'error': 'Missing employee information.'}), 400
    
    try:
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        emp_ref = db.collection('employees').document(emp_id)
        if emp_ref.get().exists:
            return jsonify({'error': 'Employee ID already exists.'}), 400
        
        emp_ref.set({
            'emp_id': emp_id,
            'name': name,
            'position': position,
            'department': department,
            'email': email,
            'phone': phone,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        logging.info(f"Employee added successfully: {emp_id}")
        return jsonify({'message': 'Employee added successfully.'}), 201
    except Exception as e:
        logging.error(f"Error adding employee: {e}")
        return jsonify({'error': 'Failed to add employee.'}), 500

@hr_bp.route('/view_employee/<emp_id>', methods=['GET'])
@token_required
def view_employee(emp_id):
    db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
    emp_ref = db.collection('employees').document(emp_id)
    emp = emp_ref.get()
    if not emp.exists:
        return jsonify({'error': 'Employee not found.'}), 404
    
    employee = emp.to_dict()
    return jsonify({'employee': employee}), 200

@hr_bp.route('/edit_employee/<emp_id>', methods=['PUT'])
@token_required
def edit_employee(emp_id):
    """
    Endpoint to edit an existing employee.
    Expects JSON payload with fields to update.
    """
    data = request.json
    updates = {}
    for key in ['name', 'position', 'department', 'email', 'phone']:
        if key in data:
            updates[key] = data[key]
    
    if not updates:
        return jsonify({'error': 'No valid fields to update.'}), 400
    
    try:
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        emp_ref = db.collection('employees').document(emp_id)
        if not emp_ref.get().exists:
            return jsonify({'error': 'Employee not found.'}), 404
        
        emp_ref.update(updates)
        logging.info(f"Employee updated successfully: {emp_id}")
        return jsonify({'message': 'Employee updated successfully.'}), 200
    except Exception as e:
        logging.error(f"Error updating employee: {e}")
        return jsonify({'error': 'Failed to update employee.'}), 500

@hr_bp.route('/delete_employee/<emp_id>', methods=['DELETE'])
@token_required
def delete_employee(emp_id):
    """
    Endpoint to delete an employee.
    """
    try:
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        emp_ref = db.collection('employees').document(emp_id)
        if not emp_ref.get().exists:
            return jsonify({'error': 'Employee not found.'}), 404
        
        emp_ref.delete()
        logging.info(f"Employee deleted successfully: {emp_id}")
        return jsonify({'message': 'Employee deleted successfully.'}), 200
    except Exception as e:
        logging.error(f"Error deleting employee: {e}")
        return jsonify({'error': 'Failed to delete employee.'}), 500
