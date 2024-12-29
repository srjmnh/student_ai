
document.addEventListener("DOMContentLoaded", () => {
    const geminiForm = document.getElementById("gemini-form");
    const geminiInput = document.getElementById("gemini-input");
    const geminiResponse = document.getElementById("gemini-response");

    geminiForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const userInput = geminiInput.value;

        // Display a loading message
        geminiResponse.innerHTML = `<p>Processing: "${userInput}"</p>`;

        try {
            // Send the input to the Gemini backend and fetch the response
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
                geminiResponse.innerHTML = `<p class="text-danger">Error: Unable to fetch response from Gemini.</p>`;
            }
        } catch (error) {
            geminiResponse.innerHTML = `<p class="text-danger">Error: ${error.message}</p>`;
        }
    });
});
