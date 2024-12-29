// app/static/js/auth.js

document.addEventListener('DOMContentLoaded', () => {
    const roleSelectionForm = document.getElementById('roleSelectionForm');
    const roleSelect = document.getElementById('roleSelect');
    const showRegister = document.getElementById('showRegister');
    const showLogin = document.getElementById('showLogin');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    // Toggle Forms
    showRegister.addEventListener('click', (e) => {
        e.preventDefault();
        registerForm.style.display = 'block';
        loginForm.style.display = 'none';
    });

    showLogin.addEventListener('click', (e) => {
        e.preventDefault();
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
    });

    // Role Selection
    roleSelectionForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const selectedRole = roleSelect.value;
        localStorage.setItem('selectedRole', selectedRole);
        alert(`Role selected: ${selectedRole}`);
        // Redirect or proceed as needed
    });

    // Firebase Registration
    const firebaseRegisterForm = document.getElementById('firebaseRegisterForm');
    firebaseRegisterForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('registerEmail').value;
        const password = document.getElementById('registerPassword').value;
        const role = document.getElementById('registerRole').value;

        try {
            const userCredential = await firebase.auth().createUserWithEmailAndPassword(email, password);
            const user = userCredential.user;
            const idToken = await user.getIdToken();

            // Send token and role to backend for additional processing
            const response = await fetch('/auth/register', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    token: idToken,
                    role: role
                })
            });

            const data = await response.json();
            if (response.status === 201) {
                alert('Registration successful. You can now log in.');
                registerForm.style.display = 'none';
                loginForm.style.display = 'block';
            } else {
                alert(`Registration failed: ${data.error}`);
                // Optionally, delete the Firebase user if backend registration fails
                await user.delete();
            }
        } catch (error) {
            console.error('Error during registration:', error);
            alert(`Registration error: ${error.message}`);
        }
    });

    // Firebase Login
    const firebaseLoginForm = document.getElementById('firebaseLoginForm');
    firebaseLoginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;

        try {
            const userCredential = await firebase.auth().signInWithEmailAndPassword(email, password);
            const user = userCredential.user;
            const idToken = await user.getIdToken();

            // Verify token with backend
            const response = await fetch('/auth/verify_token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    token: idToken
                })
            });

            const data = await response.json();
            if (response.status === 200) {
                // Store token and user info as needed (e.g., in localStorage)
                localStorage.setItem('token', idToken);
                localStorage.setItem('user', JSON.stringify(data.user));
                alert('Login successful.');
                // Redirect based on role
                if (data.user.role === 'hr') {
                    window.location.href = '/hr/dashboard';
                } else if (data.user.role === 'employee') {
                    window.location.href = '/employee/dashboard';
                }
            } else {
                alert(`Login failed: ${data.error}`);
                await firebase.auth().signOut();
            }
        } catch (error) {
            console.error('Error during login:', error);
            alert(`Login error: ${error.message}`);
        }
    });

    // Logout Functionality
    const logoutButton = document.getElementById('logoutButton');
    if (logoutButton) {
        logoutButton.addEventListener('click', async () => {
            await firebase.auth().signOut();
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            alert('Logged out successfully.');
            window.location.href = '/';
        });
    }
});