// scripts.js

// Array of random music URLs
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

// Elements
const chatBody = document.getElementById('chatBody');
const userInput = document.getElementById('userInput');
const chatSection = document.getElementById('chatSection');
const tablePanel = document.getElementById('tablePanel');
const homeScreen = document.getElementById('homeScreen');

// Toast Notification (Optional Enhancement)
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
      headers: { 'Content-Type': 'application/json' },
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
  } else {
    addBubble(reply, false);
    // Optionally, show a toast notification
    showToast("New message received.", 'success');
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
    let address = cells[4].innerText.trim();
    let phone = cells[5].innerText.trim();
    let guardian = cells[6].innerText.trim();
    let guardianPhone = cells[7].innerText.trim();
    let attendance = cells[8].innerText.trim();
    let grades = cells[9].innerText.trim();
    try {
      grades = JSON.parse(grades);
    } catch (e) { }

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
    const res = await fetch('/bulk_update_students', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
  } catch (err) {
    addBubble("Error saving changes: " + err, false);
    showToast("Error saving changes.", 'danger');
  }
  tablePanel.classList.remove('show', 'animate__slideInRight');
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

// Typing Indicator Functions
function addTypingIndicator() {
  const typingBubble = document.createElement('div');
  typingBubble.classList.add('chat-bubble', 'ai-msg', 'animate__animated', 'animate__fadeIn');
  typingBubble.id = 'typingIndicator';
  typingBubble.innerHTML = '<em>Typing...</em>';
  chatBody.appendChild(typingBubble);
  chatBody.scrollTop = chatBody.scrollHeight;
}

function removeTypingIndicator() {
  const typingBubble = document.getElementById('typingIndicator');
  if (typingBubble) {
    typingBubble.remove();
  }
}

// Ensure proper behavior on window resize for mobile responsiveness
window.addEventListener('resize', () => {
  if (window.innerWidth <= 576) {
    // Adjust elements if necessary
  }
});
