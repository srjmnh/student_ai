
document.addEventListener("DOMContentLoaded", () => {
    const geminiForm = document.getElementById("gemini-form");
    const geminiInput = document.getElementById("gemini-input");
    const geminiResponse = document.getElementById("gemini-response");

    geminiForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const userInput = geminiInput.value.trim();

        if (!userInput) {
            geminiResponse.innerHTML = `<p class="text-danger">Please enter a question.</p>`;
            return;
        }

        geminiResponse.innerHTML = `<p>Processing: "${userInput}"</p>`;

        try {
            const response = await fetch("/gemini/respond", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ query: userInput }),
            });

            if (response.ok) {
                const data = await response.json();
                geminiResponse.innerHTML = `<p><strong>Gemini:</strong> ${data.response}</p>`;
            } else {
                geminiResponse.innerHTML = `<p class="text-danger">Error: Unable to fetch Gemini response.</p>`;
            }
        } catch (error) {
            geminiResponse.innerHTML = `<p class="text-danger">Error: ${error.message}</p>`;
        }
    });
});
