// scripts.js

// Elements
const chatBody = document.getElementById('chatBody');
const userInput = document.getElementById('userInput');
const chatSection = document.getElementById('chatSection');
const tablePanel = document.getElementById('tablePanel');
const gradesSection = document.getElementById('gradesSection');
const homeScreen = document.getElementById('homeScreen');
const classDivisionFilter = document.getElementById('classDivisionFilter');

// Toast Notification
const toastElement = document.getElementById('liveToast');
const toastBody = document.getElementById('toastBody');
const bsToast = new bootstrap.Toast(toastElement);

// Firebase configuration
const firebaseConfig = {
  apiKey: "YOUR_FIREBASE_API_KEY",
  authDomain: "YOUR_FIREBASE_AUTH_DOMAIN",
  projectId: "YOUR_FIREBASE_PROJECT_ID",
  storageBucket: "YOUR_FIREBASE_STORAGE_BUCKET",
  messagingSenderId: "YOUR_FIREBASE_MESSAGING_SENDER_ID",
  appId: "YOUR_FIREBASE_APP_ID"
};

// Initialize Firebase
firebase.initializeApp(firebaseConfig);
const db = firebase.firestore();

// Function to show toast
function showToast(message, type = 'primary') {
  toastBody.innerText = message;
  toastElement.classList.remove('text-bg-primary', 'text-bg-success', 'text-bg-danger', 'text-bg-warning', 'text-bg-info', 'text-bg-secondary');
  toastElement.classList.add(`text-bg-${type}`);
  bsToast.show();
}

// Function to add chat bubbles
function addBubble(text, isUser = false) {
  const bubble = document.createElement('div');
  bubble.classList.add('chat-bubble', isUser ? 'user-msg' : 'ai-msg', 'animate__animated', 'animate__fadeInUp');
  bubble.innerHTML = text;
  chatBody.appendChild(bubble);
  chatBody.scrollTop = chatBody.scrollHeight;
}

// Function to send user prompt
async function sendPrompt() {
  const prompt = userInput.value.trim();
  if (!prompt) return;
  addBubble(prompt, true);
  userInput.value = '';

  addTypingIndicator();

  try {
    const resp = await fetch('/process_prompt', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ prompt })
    });
    const data = await resp.json();
    const reply = data.message || data.error || 'No response.';
    removeTypingIndicator();
    parseReply(reply);
  } catch (err) {
    removeTypingIndicator();
    addBubble("Error connecting to server: " + err, false);
    showToast("Error connecting to server.", 'danger');
  }
}

// Function to parse AI reply
function parseReply(reply) {
  // If reply includes <table or 'slideFromRight', we show in tablePanel
  if (reply.includes('<table') || reply.includes('slideFromRight')) {
    tablePanel.innerHTML = reply;
    tablePanel.classList.add('show', 'animate__animated', 'animate__slideInRight');
    chatSection.classList.add('slideLeft');
    initializeTableFunctionality(); // Initialize delete and add functionalities
    populateClassDivisionFilter(); // Populate the class-division filter dropdown
  } else {
    addBubble(reply, false);
    // Optionally, show a toast notification
    showToast("New message received.", 'success');
  }
}

// Function to initialize table functionalities (delete and add)
function initializeTableFunctionality() {
  // Add event listeners to delete icons
  const deleteButtons = tablePanel.querySelectorAll('.btn-delete-row');
  deleteButtons.forEach(button => {
    button.addEventListener('click', () => {
      const row = button.closest('tr');
      const studentId = row.querySelector('.student-id').innerText.trim();
      if (studentId === 'ID') {
        showToast("Cannot delete header row.", 'warning');
        return;
      }
      if (confirm(`Are you sure you want to delete student ID ${studentId}?`)) {
        deleteStudent(studentId, row);
      }
    });
  });
}

// Function to delete a student via API
async function deleteStudent(studentId, rowElement) {
  try {
    const resp = await fetch('/process_prompt', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ prompt: `delete_student {"id": "${studentId}"}` })
    });
    const data = await resp.json();
    if (data.message) {
      showToast(data.message, 'success');
      // Remove the row from the table
      rowElement.remove();
    } else if (data.error) {
      showToast(data.error, 'danger');
    }
  } catch (err) {
    showToast("Error deleting student.", 'danger');
  }
}

// Function to add a new row to the table
function addNewRow() {
  const tbody = tablePanel.querySelector('table tbody');
  const newRow = document.createElement('tr');

  newRow.innerHTML = `
    <td class="student-id" contenteditable="false">ID</td>
    <td contenteditable="true">Name</td>
    <td contenteditable="true">Age</td>
    <td contenteditable="true" class="class-cell">Class</td>
    <td contenteditable="true" class="division-cell">Division</td>
    <td contenteditable="true">Address</td>
    <td contenteditable="true">Phone</td>
    <td contenteditable="true">Guardian</td>
    <td contenteditable="true">Guardian Phone</td>
    <td contenteditable="true">Attendance</td>
    <td contenteditable="true">Grades</td>
    <td>
      <button class="btn btn-danger btn-delete-row" aria-label="Delete Row">
        <i class="fas fa-trash-alt"></i>
      </button>
    </td>
  `;

  tbody.appendChild(newRow);
  initializeTableFunctionality(); // Re-initialize to attach event listeners to new delete button
}

// Function to save table edits
async function saveTableEdits() {
  const rows = tablePanel.querySelectorAll('table tbody tr');
  const updates = [];
  rows.forEach(r => {
    const cells = r.querySelectorAll('td');
    if (!cells.length) return;
    const sid = cells[0].innerText.trim();
    if (!sid || sid === 'ID') return; // Skip rows without valid IDs

    let name = cells[1].innerText.trim();
    let age = cells[2].innerText.trim();
    let sclass = cells[3].innerText.trim();
    let division = cells[4].innerText.trim();
    let address = cells[5].innerText.trim();
    let phone = cells[6].innerText.trim();
    let guardian = cells[7].innerText.trim();
    let guardianPhone = cells[8].innerText.trim();
    let attendance = cells[9].innerText.trim();
    let grades = cells[10].innerText.trim();
    try {
      grades = JSON.parse(grades);
    } catch (e) { }

    // Validation: Ensure 'name', 'class', and 'division' are provided
    if (!name || !sclass || !division) {
      showToast(`Student ID ${sid} is missing 'Name', 'Class', or 'Division'. Please fill them in.`, 'warning');
      return;
    }

    updates.push({
      id: sid,
      name,
      age: _safe_int(age),
      class: sclass,
      division: division,
      address,
      phone,
      guardian_name: guardian,
      guardian_phone: guardianPhone,
      attendance,
      grades
    });
  });

  if (updates.length === 0) {
    showToast("No valid changes to save.", 'warning');
    return;
  }

  try {
    const res = await fetch('/bulk_update_students', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ updates })
    });
    const data = await res.json();
    if (data.success) {
      addBubble("Changes saved to Firebase!", false);
      showToast("Changes saved successfully!", 'success');
    } else {
      addBubble("Error saving changes: " + (data.error || 'unknown'), false);
      showToast("Error saving changes.", 'danger');
    }
    tablePanel.classList.remove('show', 'animate__slideInRight');
    chatSection.classList.remove('slideLeft');
  } catch (err) {
    addBubble("Error saving changes: " + err, false);
    showToast("Error saving changes.", 'danger');
  }
}

// Function to populate class and division filter dropdown
function populateClassDivisionFilter() {
  const select = classDivisionFilter;
  // Clear existing options except the first
  while (select.options.length > 1) {
    select.remove(1);
  }

  // Fetch unique class-division combinations from Firestore
  fetch('/get_unique_class_divisions', {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json'
    }
  })
    .then(response => response.json())
    .then(data => {
      const classDivisions = data.class_divisions || [];
      classDivisions.forEach(cd => {
        const option = document.createElement('option');
        option.value = cd; // e.g., "5B"
        option.textContent = cd;
        select.appendChild(option);
      });
    })
    .catch(err => {
      console.error("Error fetching class-divisions:", err);
      showToast("Error fetching class-divisions.", 'danger');
    });
}

// Function to filter students by class and division
function filterStudentsByClassDivision() {
  const selectedClassDiv = classDivisionFilter.value;
  const rows = tablePanel.querySelectorAll('table tbody tr');
  rows.forEach(row => {
    const classCell = row.querySelector('.class-cell').innerText.trim();
    const divisionCell = row.querySelector('.division-cell').innerText.trim();
    const combined = `${classCell}${divisionCell}`;
    if (selectedClassDiv === "" || combined === selectedClassDiv) {
      row.style.display = "";
    } else {
      row.style.display = "none";
    }
  });
}

// Function to toggle Grades Panel
function toggleGradesPanel() {
  const isOpen = gradesSection.classList.contains('show');
  if (isOpen) {
    closeGradesPanel();
  } else {
    openGradesPanel();
  }
}

// Grades Section Functions

// Function to open Grades Panel
function openGradesPanel() {
  fetch('/get_grades', {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json'
    }
  })
    .then(response => response.json())
    .then(data => {
      if (data.grades) {
        renderGradesTable(data.grades);
        gradesSection.classList.add('show', 'animate__animated', 'animate__slideInRight');
      } else {
        showToast("Failed to load grades.", 'danger');
      }
    })
    .catch(err => {
      console.error("Error fetching grades:", err);
      showToast("Error fetching grades.", 'danger');
    });
}

// Function to close Grades Panel
function closeGradesPanel() {
  gradesSection.classList.remove('show', 'animate__slideInRight');
}

// Function to render Grades Table
function renderGradesTable(grades) {
  let html = `
    <table class="table table-bordered table-sm">
      <thead>
        <tr>
          <th>Subject ID</th>
          <th>Subject Name</th>
          <th>Student ID</th>
          <th>Term 1</th>
          <th>Term 2</th>
          <th>Term 3</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
  `;

  grades.forEach(subject => {
    const subject_id = subject.subject_id;
    const subject_name = subject.subject_name;
    const marks = subject.marks || {};

    for (const [student_id, terms] of Object.entries(marks)) {
      html += `
        <tr>
          <td>${subject_id}</td>
          <td>${subject_name}</td>
          <td>${student_id}</td>
          <td contenteditable="true">${terms.term1 || ''}</td>
          <td contenteditable="true">${terms.term2 || ''}</td>
          <td contenteditable="true">${terms.term3 || ''}</td>
          <td>
            <button class="btn btn-danger btn-delete-grade" onclick="deleteGrade('${subject_id}', '${student_id}')">
              <i class="fas fa-trash-alt"></i>
            </button>
          </td>
        </tr>
      `;
    }
  });

  html += `
      </tbody>
    </table>
  `;

  gradesSection.querySelector('#gradesContent').innerHTML = html;
}

// Function to save Grades Edits
async function saveGradesEdits() {
  const rows = gradesSection.querySelectorAll('#gradesContent table tbody tr');
  const updates = [];

  rows.forEach(row => {
    const cells = row.querySelectorAll('td');
    const subject_id = cells[0].innerText.trim();
    const subject_name = cells[1].innerText.trim();
    const student_id = cells[2].innerText.trim();
    const term1 = parseInt(cells[3].innerText.trim()) || 0;
    const term2 = parseInt(cells[4].innerText.trim()) || 0;
    const term3 = parseInt(cells[5].innerText.trim()) || 0;

    updates.push({
      subject_id,
      subject_name,
      student_id,
      term: "term1",
      marks: term1
    }, {
      subject_id,
      subject_name,
      student_id,
      term: "term2",
      marks: term2
    }, {
      subject_id,
      subject_name,
      student_id,
      term: "term3",
      marks: term3
    });
  });

  // Send updates to the backend
  for (const update of updates) {
    try {
      const res = await fetch('/update_grades', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(update)
      });
      const data = await res.json();
      if (data.message) {
        showToast(data.message, 'success');
      } else if (data.error) {
        showToast(data.error, 'danger');
      }
    } catch (err) {
      console.error("Error updating grades:", err);
      showToast("Error updating grades.", 'danger');
    }
  }

  // Refresh the grades table
  openGradesPanel();
}

// Function to delete a grade entry
async function deleteGrade(subject_id, student_id) {
  if (!confirm(`Are you sure you want to delete grades for student ID ${student_id} in subject ${subject_id}?`)) {
    return;
  }

  try {
    const res = await fetch('/delete_grade', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ subject_id, student_id })
    });
    const data = await res.json();
    if (data.message) {
      showToast(data.message, 'success');
      openGradesPanel();
    } else if (data.error) {
      showToast(data.error, 'danger');
    }
  } catch (err) {
    console.error("Error deleting grade:", err);
    showToast("Error deleting grade.", 'danger');
  }
}

// Function to save table edits
async function saveTableEdits() {
  const rows = tablePanel.querySelectorAll('table tbody tr');
  const updates = [];
  rows.forEach(r => {
    const cells = r.querySelectorAll('td');
    if (!cells.length) return;
    const sid = cells[0].innerText.trim();
    if (!sid || sid === 'ID') return; // Skip rows without valid IDs

    let name = cells[1].innerText.trim();
    let age = cells[2].innerText.trim();
    let sclass = cells[3].innerText.trim();
    let division = cells[4].innerText.trim();
    let address = cells[5].innerText.trim();
    let phone = cells[6].innerText.trim();
    let guardian = cells[7].innerText.trim();
    let guardianPhone = cells[8].innerText.trim();
    let attendance = cells[9].innerText.trim();
    let grades = cells[10].innerText.trim();
    try {
      grades = JSON.parse(grades);
    } catch (e) { }

    // Validation: Ensure 'name', 'class', and 'division' are provided
    if (!name || !sclass || !division) {
      showToast(`Student ID ${sid} is missing 'Name', 'Class', or 'Division'. Please fill them in.`, 'warning');
      return;
    }

    updates.push({
      id: sid,
      name,
      age: _safe_int(age),
      class: sclass,
      division: division,
      address,
      phone,
      guardian_name: guardian,
      guardian_phone: guardianPhone,
      attendance,
      grades
    });
  });

  if (updates.length === 0) {
    showToast("No valid changes to save.", 'warning');
    return;
  }

  try {
    const res = await fetch('/bulk_update_students', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ updates })
    });
    const data = await res.json();
    if (data.success) {
      addBubble("Changes saved to Firebase!", false);
      showToast("Changes saved successfully!", 'success');
    } else {
      addBubble("Error saving changes: " + (data.error || 'unknown'), false);
      showToast("Error saving changes.", 'danger');
    }
    tablePanel.classList.remove('show', 'animate__slideInRight');
    chatSection.classList.remove('slideLeft');
  } catch (err) {
    addBubble("Error saving changes: " + err, false);
    showToast("Error saving changes.", 'danger');
  }
}

// Dark Mode Toggle Function
function toggleDarkMode() {
  document.body.classList.toggle('dark-mode');
  const toggleBtn = document.querySelector('.dark-toggle');
  if (document.body.classList.contains('dark-mode')) {
    toggleBtn.textContent = '☀️ Light Mode';
    showToast("Dark mode enabled.", 'secondary');
    localStorage.setItem('dark-mode', 'enabled');
  } else {
    toggleBtn.textContent = '🌙 Dark Mode';
    showToast("Light mode enabled.", 'secondary');
    localStorage.setItem('dark-mode', 'disabled');
  }
}

// Initialize the toggle button text based on saved preference
window.addEventListener('load', () => {
  const toggleBtn = document.querySelector('.dark-toggle');
  // Check if dark mode was previously enabled
  const darkMode = localStorage.getItem('dark-mode');
  if (darkMode === 'enabled') {
    document.body.classList.add('dark-mode');
    toggleBtn.textContent = '☀️ Light Mode';
  } else {
    toggleBtn.textContent = '🌙 Dark Mode';
  }
});

// Home Screen Functionality
function hideHomeScreen() {
  homeScreen.classList.add('animate__animated', 'animate__fadeOut');
  // After transition, hide the home screen completely and show chat
  setTimeout(() => {
    homeScreen.style.display = 'none';
    chatSection.classList.add('show');
  }, 500); // Match the animation duration in CSS (0.5s)
}

// Close Table Panel Function
function closeTablePanel() {
  tablePanel.classList.remove('show', 'animate__slideInRight');
  chatSection.classList.remove('slideLeft');
}

// Close Grades Panel Function
function closeGradesPanel() {
  gradesSection.classList.remove('show', 'animate__slideInRight');
}

// Function to delete a grade entry
async function deleteGrade(subject_id, student_id) {
  if (!confirm(`Are you sure you want to delete grades for student ID ${student_id} in subject ${subject_id}?`)) {
    return;
  }

  try {
    const res = await fetch('/delete_grade', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ subject_id, student_id })
    });
    const data = await res.json();
    if (data.message) {
      showToast(data.message, 'success');
      openGradesPanel();
    } else if (data.error) {
      showToast(data.error, 'danger');
    }
  } catch (err) {
    console.error("Error deleting grade:", err);
    showToast("Error deleting grade.", 'danger');
  }
}

// Function to add typing indicator
function addTypingIndicator() {
  const typingBubble = document.createElement('div');
  typingBubble.classList.add('chat-bubble', 'ai-msg', 'animate__animated', 'animate__fadeIn');
  typingBubble.id = 'typingIndicator';
  typingBubble.innerHTML = '<em>Typing...</em>';
  chatBody.appendChild(typingBubble);
  chatBody.scrollTop = chatBody.scrollHeight;
}

// Function to remove typing indicator
function removeTypingIndicator() {
  const typingBubble = document.getElementById('typingIndicator');
  if (typingBubble) {
    typingBubble.remove();
  }
}
