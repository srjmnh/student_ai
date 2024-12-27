# app/blueprints/students/routes.py

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify
)
from app.utils.decorators import login_required, roles_required
import json
import random
from datetime import datetime
import hashlib  # If used for password hashing or other purposes

students_bp = Blueprint('students', __name__, template_folder='templates')

# Utility Functions
def generate_student_id(name, age, division):
    """
    Generates a unique student ID based on the student's name, age, division, and a random number.
    """
    db = current_app.db
    existing_ids = [doc.id for doc in db.collection('students').stream()]
    r = random.randint(1000, 9999)
    part = (name[:4].upper() if len(name) >= 4 else name.upper())
    a = str(age) if age else "00"
    d = division.upper()
    sid = f"{part}{a}{d}{r}"
    while sid in existing_ids:
        r = random.randint(1000, 9999)
        sid = f"{part}{a}{d}{r}"
    return sid

def generate_subject_id(subject_name):
    """
    Generates a unique subject ID based on the subject name and a random number.
    """
    db = current_app.db
    existing_ids = [doc.id for doc in db.collection('grades').stream()]
    r = random.randint(1000, 9999)
    base = subject_name.lower().replace(" ", "_")
    subject_id = f"{base}_{r}"
    while subject_id in existing_ids:
        r = random.randint(1000, 9999)
        subject_id = f"{base}_{r}"
    return subject_id

# Route Definitions

@students_bp.route('/')
@login_required
@roles_required('admin', 'teacher')
def view_students():
    """
    Displays a list of all students.
    Accessible by users with roles 'admin' and 'teacher'.
    """
    db = current_app.db
    students_ref = db.collection('students')
    students = [doc.to_dict() for doc in students_ref.stream()]
    return render_template('students/view_students.html', students=students)

@students_bp.route('/add', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def add_student():
    """
    Adds a new student to the system.
    Accessible only by users with the 'admin' role.
    """
    if request.method == 'POST':
        data = request.form.to_dict()
        required_fields = ['name', 'class', 'division']
        if not all(field in data and data[field].strip() for field in required_fields):
            flash("Name, Class, and Division are required.", "danger")
            return redirect(url_for('students.add_student'))
        
        name = data['name'].strip()
        age = int(data['age']) if data.get('age') and data['age'].isdigit() else None
        sclass = data['class'].strip()
        division = data['division'].strip()
        address = data.get('address', '').strip()
        phone = data.get('phone', '').strip()
        guardian_name = data.get('guardian_name', '').strip()
        guardian_phone = data.get('guardian_phone', '').strip()
        attendance = int(data['attendance']) if data.get('attendance') and data['attendance'].isdigit() else 0
        
        # Generate unique student ID
        sid = generate_student_id(name, age, division)
        
        student_data = {
            "id": sid,
            "name": name,
            "age": age,
            "class": sclass,
            "division": division,
            "address": address,
            "phone": phone,
            "guardian_name": guardian_name,
            "guardian_phone": guardian_phone,
            "attendance": attendance,
            "grades": {},
            "grades_history": []
        }
        
        try:
            db = current_app.db
            db.collection('students').document(sid).set(student_data)
            flash(f"Student {name} added successfully with ID {sid}.", "success")
            return redirect(url_for('students.view_students'))
        except Exception as e:
            current_app.logger.error(f"Error adding student: {e}")
            flash("An error occurred while adding the student.", "danger")
            return redirect(url_for('students.add_student'))
    
    return render_template('students/add_student.html')

@students_bp.route('/edit/<sid>', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'teacher')
def edit_student(sid):
    """
    Edits an existing student's details.
    Accessible by users with roles 'admin' and 'teacher'.
    """
    db = current_app.db
    student_ref = db.collection('students').document(sid)
    student = student_ref.get()
    if not student.exists:
        flash("Student not found.", "danger")
        return redirect(url_for('students.view_students'))
    
    if request.method == 'POST':
        data = request.form.to_dict()
        updates = {}
        for key in ['name', 'age', 'class', 'division', 'address', 'phone', 'guardian_name', 'guardian_phone']:
            if key in data:
                if key == 'age':
                    updates[key] = int(data[key]) if data[key].isdigit() else None
                else:
                    updates[key] = data[key].strip()
        
        # Update grades history if grades are updated
        if 'grades' in data and data['grades'].strip():
            try:
                new_grades = json.loads(data['grades'])
                old_grades = student.to_dict().get('grades', {})
                grades_history = student.to_dict().get('grades_history', [])
                grades_history.append({
                    "old": old_grades,
                    "new": new_grades,
                    "updated_at": datetime.utcnow()
                })
                updates['grades'] = new_grades
                updates['grades_history'] = grades_history
            except json.JSONDecodeError:
                flash("Invalid grades format. Please provide valid JSON.", "danger")
                return redirect(url_for('students.edit_student', sid=sid))
        
        try:
            student_ref.update(updates)
            flash("Student details updated successfully.", "success")
            return redirect(url_for('students.view_students'))
        except Exception as e:
            current_app.logger.error(f"Error updating student: {e}")
            flash("An error occurred while updating the student details.", "danger")
            return redirect(url_for('students.edit_student', sid=sid))
    
    student_data = student.to_dict()
    return render_template('students/edit_student.html', student=student_data)

@students_bp.route('/delete/<sid>', methods=['POST'])
@login_required
@roles_required('admin')
def delete_student(sid):
    """
    Deletes a student from the system.
    Accessible only by users with the 'admin' role.
    """
    db = current_app.db
    student_ref = db.collection('students').document(sid)
    student = student_ref.get()
    if not student.exists:
        return jsonify({"error": "Student not found."}), 404
    try:
        student_ref.delete()
        return jsonify({"success": True, "message": f"Student {sid} deleted successfully."}), 200
    except Exception as e:
        current_app.logger.error(f"Error deleting student: {e}")
        return jsonify({"error": "An error occurred while deleting the student."}), 500

@students_bp.route('/search', methods=['GET'])
@login_required
@roles_required('admin', 'teacher')
def search_students():
    """
    Searches for students based on query parameters.
    Accessible by users with roles 'admin' and 'teacher'.
    """
    query = request.args.get('q', '').strip()
    db = current_app.db
    students_ref = db.collection('students')
    
    if not query:
        flash("Please enter a search term.", "warning")
        return redirect(url_for('students.view_students'))
    
    # Simple search implementation: search by name, class, or division
    students = []
    try:
        # Firestore doesn't support OR queries directly; perform multiple queries
        name_query = students_ref.where('name', '>=', query).where('name', '<=', query + '\uf8ff').stream()
        class_query = students_ref.where('class', '==', query).stream()
        division_query = students_ref.where('division', '==', query.upper()).stream()
        
        students = [doc.to_dict() for doc in name_query]
        students += [doc.to_dict() for doc in class_query]
        students += [doc.to_dict() for doc in division_query]
        
        # Remove duplicates
        unique_students = {student['id']: student for student in students}
        students = list(unique_students.values())
        
        if not students:
            flash("No students found matching your query.", "info")
        
        return render_template('students/view_students.html', students=students)
    except Exception as e:
        current_app.logger.error(f"Error searching students: {e}")
        flash("An error occurred while searching for students.", "danger")
        return redirect(url_for('students.view_students'))

@students_bp.route('/bulk_add', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def bulk_add_students():
    """
    Adds multiple students at once via a JSON input.
    Accessible only by users with the 'admin' role.
    """
    if request.method == 'POST':
        data = request.form.get('students_json', '').strip()
        if not data:
            flash("Please provide student data in JSON format.", "danger")
            return redirect(url_for('students.bulk_add_students'))
        
        try:
            students_list = json.loads(data)
            if not isinstance(students_list, list):
                flash("Invalid JSON format. Expected a list of students.", "danger")
                return redirect(url_for('students.bulk_add_students'))
            
            db = current_app.db
            for student in students_list:
                name = student.get('name', '').strip()
                age = int(student['age']) if student.get('age') and str(student['age']).isdigit() else None
                sclass = student.get('class', '').strip()
                division = student.get('division', '').strip()
                address = student.get('address', '').strip()
                phone = student.get('phone', '').strip()
                guardian_name = student.get('guardian_name', '').strip()
                guardian_phone = student.get('guardian_phone', '').strip()
                attendance = int(student.get('attendance', 0)) if str(student.get('attendance')).isdigit() else 0
                
                if not name or not sclass or not division:
                    flash(f"Skipping student with incomplete data: {student}", "warning")
                    continue
                
                sid = generate_student_id(name, age, division)
                
                student_data = {
                    "id": sid,
                    "name": name,
                    "age": age,
                    "class": sclass,
                    "division": division,
                    "address": address,
                    "phone": phone,
                    "guardian_name": guardian_name,
                    "guardian_phone": guardian_phone,
                    "attendance": attendance,
                    "grades": {},
                    "grades_history": []
                }
                
                db.collection('students').document(sid).set(student_data)
            
            flash("Bulk student addition completed.", "success")
            return redirect(url_for('students.view_students'))
        except json.JSONDecodeError:
            flash("Invalid JSON format. Please ensure your data is correctly structured.", "danger")
            return redirect(url_for('students.bulk_add_students'))
        except Exception as e:
            current_app.logger.error(f"Error bulk adding students: {e}")
            flash("An error occurred while adding students.", "danger")
            return redirect(url_for('students.bulk_add_students'))
    
    return render_template('students/bulk_add_students.html')
