from firebase_setup import db

def add_student(params):
    try:
        db.collection('students').add(params)
        return f"✅ Student {params['name']} added successfully!"
    except Exception as e:
        print(f"❌ Error adding student: {e}")
        return f"Error: {str(e)}"

def update_student(params):
    try:
        student_id = params.get('id')
        db.collection('students').document(student_id).update(params)
        return f"✅ Student with ID {student_id} updated successfully!"
    except Exception as e:
        print(f"❌ Error updating student: {e}")
        return f"Error: {str(e)}"

def delete_student(params):
    try:
        student_id = params.get('id')
        db.collection('students').document(student_id).delete()
        return f"✅ Student with ID {student_id} deleted successfully!"
    except Exception as e:
        print(f"❌ Error deleting student: {e}")
        return f"Error: {str(e)}"

def view_students():
    try:
        students_ref = db.collection('students')
        students = students_ref.stream()
        student_list = [student.to_dict() for student in students]
        return student_list
    except Exception as e:
        print(f"❌ Error viewing students: {e}")
        return f"Error: {str(e)}"