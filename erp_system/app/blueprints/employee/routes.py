from flask import jsonify, request, current_app
from app.blueprints.employee import employee_bp
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
            if user_data.get('role') != 'employee':
                return jsonify({'error': 'Unauthorized access.'}), 403
            # Attach user info to the request context if needed
            request.user = {
                'uid': uid,
                'email': user_data.get('email'),
                'role': user_data.get('role'),
                'emp_id': user_data.get('emp_id')
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

@employee_bp.route('/dashboard', methods=['GET'])
@token_required
def dashboard():
    db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
    uid = request.user['uid']
    
    # Fetch user data
    user_doc = db.collection('users').document(uid).get()
    user_data = user_doc.to_dict()
    emp_id = user_data.get('emp_id')
    
    # Fetch employee details
    emp_ref = db.collection('employees').document(emp_id)
    emp = emp_ref.get()
    if not emp.exists:
        return jsonify({'error': 'Employee data not found.'}), 404
    
    employee = emp.to_dict()
    
    # Fetch leave requests
    leaves = db.collection('leaves').where('emp_id', '==', emp_id).stream()
    leave_requests = [leave.to_dict() for leave in leaves]
    
    return jsonify({'employee': employee, 'leave_requests': leave_requests}), 200

@employee_bp.route('/submit_leave', methods=['POST'])
@token_required
def submit_leave():
    """
    Endpoint to submit a leave request.
    Expects JSON payload with 'start_date', 'end_date', 'reason'.
    """
    data = request.json
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    reason = data.get('reason')
    
    if not all([start_date, end_date, reason]):
        return jsonify({'error': 'Missing leave information.'}), 400
    
    try:
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        uid = request.user['uid']
        user_doc = db.collection('users').document(uid).get()
        user_data = user_doc.to_dict()
        emp_id = user_data.get('emp_id')
        
        # Create leave request
        leave_ref = db.collection('leaves').document()
        leave_ref.set({
            'leave_id': leave_ref.id,
            'emp_id': emp_id,
            'start_date': start_date,
            'end_date': end_date,
            'reason': reason,
            'status': 'Pending',
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        logging.info(f"Leave request submitted by {emp_id}")
        return jsonify({'message': 'Leave request submitted successfully.'}), 201
    except Exception as e:
        logging.error(f"Error submitting leave request: {e}")
        return jsonify({'error': 'Failed to submit leave request.'}), 500

@employee_bp.route('/view_leave/<leave_id>', methods=['GET'])
@token_required
def view_leave(leave_id):
    db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
    leave_ref = db.collection('leaves').document(leave_id)
    leave = leave_ref.get()
    if not leave.exists:
        return jsonify({'error': 'Leave request not found.'}), 404
    
    leave_data = leave.to_dict()
    return jsonify({'leave': leave_data}), 200
