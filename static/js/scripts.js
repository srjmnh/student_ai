// scripts.js

// Elements
const chatBody = document.getElementById('chatBody');
const userInput = document.getElementById('userInput');
const chatSection = document.getElementById('chatSection');
const tablePanel = document.getElementById('tablePanel');
const gradesPanel = document.getElementById('gradesPanel'); // New Grades Panel
const bgMusic = document.getElementById('bgMusic');

// Toast Notification
const toastElement = document.getElementById('liveToast');
const toastBody = document.getElementById('toastBody');
const bsToast = new bootstrap.Toast(toastElement);

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
    if (reply.includes('<table') || reply.includes('slideFromRight')) {
        tablePanel.innerHTML = reply;
        addDeleteIcons();
        tablePanel.classList.add('show', 'animate__animated', 'animate__slideInRight');
        chatSection.classList.add('slideLeft');
    } else if (reply.includes('<h4>Student Grades</h4>')) { // Detect Grades Section
        gradesPanel.innerHTML = reply;
        addDeleteGradeButtons();
        gradesPanel.classList.add('show', 'animate__animated', 'animate__slideInRight');
        chatSection.classList.add('slideLeft');
    } else {
        addBubble(reply, false);
        showToast("New message received.", 'success');
    }
}

// Function to add delete icons for student table
function addDeleteIcons() {
    const table = tablePanel.querySelector('table');
    if (!table) return;
    // Add Action column if not present
    const headRow = table.querySelector('thead tr');
    if (headRow && !headRow.querySelector('.action-col')) {
        const th = document.createElement('th');
        th.textContent = 'Action';
        th.classList.add('action-col');
        headRow.appendChild(th);
    }
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    tbody.querySelectorAll('tr').forEach(tr => {
        let cells = tr.querySelectorAll('td');
        if (cells.length > 0 && !tr.querySelector('.action-col')) {
            const sid = cells[0].innerText.trim();
            const td = document.createElement('td');
            td.classList.add('action-col');
            td.innerHTML = `<button class="btn btn-danger btn-delete-row" onclick="deleteRow('${sid}')">🗑️</button>`;
            tr.appendChild(td);
        }
    });
}

// Function to delete a student via API
async function deleteRow(sid) {
    try {
        const resp = await fetch('/delete_by_id', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ id: sid })
        });
        const data = await resp.json();
        if (data.success) {
            addBubble(data.message, false);
            // Re-view students
            const vresp = await fetch('/process_prompt', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ prompt: 'view_students' })
            });
            const vdata = await vresp.json();
            parseReply(vdata.message);
        } else {
            addBubble("Delete error: " + (data.error || data.message), false);
        }
    } catch (err) {
        addBubble("Delete error: " + err, false);
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
        if (!sid) return;
        let name = cells[1].innerText.trim();
        let age = cells[2].innerText.trim();
        let sclass = cells[3].innerText.trim();
        let division = cells[4].innerText.trim(); // Division
        let address = cells[5].innerText.trim();
        let phone = cells[6].innerText.trim();
        let guardian = cells[7].innerText.trim();
        let guardianPhone = cells[8].innerText.trim();
        let attendance = cells[9].innerText.trim();
        let grades = cells[10].innerText.trim();
        try { grades = JSON.parse(grades); } catch(e){}
        updates.push({
            id: sid,
            name,
            age,
            class: sclass,
            division, // Include division
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
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ updates })
        });
        const data = await resp.json();
        if (data.success) {
            addBubble("Changes saved to Firebase!", false);
            showToast("Changes saved successfully!", 'success');
        } else {
            addBubble("Error saving changes: " + (data.error || data.message), false);
            showToast("Error saving changes.", 'danger');
        }
        tablePanel.classList.remove('show', 'animate__slideInRight');
        chatSection.classList.remove('slideLeft');
    } catch (err) {
        addBubble("Error saving changes: " + err, false);
        showToast("Error saving changes.", 'danger');
    }
}

// Function to add delete buttons for grades table
function addDeleteGradeButtons() {
    const table = gradesPanel.querySelector('table');
    if (!table) return;
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    tbody.querySelectorAll('tr').forEach(tr => {
        const cells = tr.querySelectorAll('td');
        if (cells.length > 0 && !tr.querySelector('.action-col')) {
            const subject_id = cells[0].innerText.trim();
            const student_id = cells[2].innerText.trim();
            const td = document.createElement('td');
            td.classList.add('action-col');
            td.innerHTML = `<button class="btn btn-danger btn-delete-grade" onclick="deleteGrade('${subject_id}', '${student_id}')">🗑️</button>`;
            tr.appendChild(td);
        }
    });
}

// Function to delete a grade via API
async function deleteGrade(subject_id, student_id) {
    if (!confirm(`Are you sure you want to delete grades for student ID ${student_id} in subject ${subject_id}?`)) {
        return;
    }

    try {
        const resp = await fetch('/delete_grade', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ subject_id, student_id })
        });
        const data = await resp.json();
        if (data.message) {
            addBubble(data.message, false);
            // Refresh grades view
            const vresp = await fetch('/process_prompt', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ prompt: 'view_grades' })
            });
            const vdata = await vresp.json();
            parseReply(vdata.message);
        } else {
            addBubble("Delete error: " + (data.error || data.message), false);
        }
    } catch (err) {
        addBubble("Delete error: " + err, false);
    }
}

// Function to save grades edits
async function saveGradesEdits() {
    const rows = gradesPanel.querySelectorAll('table tbody tr');
    const updates = [];

    rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        const subject_id = cells[0].innerText.trim();
        const student_id = cells[2].innerText.trim();
        const term1 = cells[3].innerText.trim();
        const term2 = cells[4].innerText.trim();
        const term3 = cells[5].innerText.trim();

        updates.push({
            subject_id,
            student_id,
            term: "term1",
            marks: parseInt(term1) || 0
        }, {
            subject_id,
            student_id,
            term: "term2",
            marks: parseInt(term2) || 0
        }, {
            subject_id,
            student_id,
            term: "term3",
            marks: parseInt(term3) || 0
        });
    });

    // Send updates to the backend
    for (const update of updates) {
        try {
            const res = await fetch('/update_grade', {
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

    // Refresh grades view
    try {
        const vresp = await fetch('/process_prompt', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ prompt: 'view_grades' })
        });
        const vdata = await vresp.json();
        parseReply(vdata.message);
        showToast("Grades updated successfully!", 'success');
    } catch (err) {
        console.error("Error refreshing grades:", err);
        showToast("Error refreshing grades.", 'danger');
    }
}

// Function to toggle Grades Panel
function toggleGradesPanel() {
    const isOpen = gradesPanel.classList.contains('show');
    if (isOpen) {
        closeGradesPanel();
    } else {
        openGradesPanel();
    }
}

// Function to open Grades Panel
async function openGradesPanel() {
    try {
        const resp = await fetch('/process_prompt', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ prompt: 'view_grades' })
        });
        const data = await resp.json();
        parseReply(data.message);
    } catch (err) {
        addBubble("Error loading grades: " + err, false);
    }
}

// Function to close Grades Panel
function closeGradesPanel() {
    gradesPanel.classList.remove('show', 'animate__slideInRight');
    chatSection.classList.remove('slideLeft');
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

    // Initialize background music
    const musicTracks = [
        "https://www.bensound.com/bensound-music/bensound-anewbeginning.mp3",
        "https://www.bensound.com/bensound-music/bensound-ukulele.mp3",
        "https://www.bensound.com/bensound-music/bensound-funnysong.mp3"
    ];
    const randomUrl = musicTracks[Math.floor(Math.random() * musicTracks.length)];
    bgMusic.src = randomUrl;
});

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