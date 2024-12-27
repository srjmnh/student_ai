// app/static/js/scripts.js

// Add any custom JavaScript here
// For example, handling form submissions, dynamic table updates, etc.

// Example: Confirm deletion
document.addEventListener('DOMContentLoaded', () => {
    const deleteButtons = document.querySelectorAll('.delete-student, .delete-grade');
    deleteButtons.forEach(button => {
        button.addEventListener('click', () => {
            const confirmMessage = button.classList.contains('delete-student') ?
                'Are you sure you want to delete this student?' :
                'Are you sure you want to delete this grade entry?';
            if(!confirm(confirmMessage)) {
                event.preventDefault();
            }
        });
    });
});