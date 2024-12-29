import logging
import google.generativeai as genai
from flask import current_app

class GeminiIntegration:
    def __init__(self, app):
        self.app = app
        self.configure_gemini()

    def configure_gemini(self):
        GEMINI_API_KEY = self.app.config.get("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            logging.error("GEMINI_API_KEY environment variable not set.")
            raise ValueError("GEMINI_API_KEY environment variable not set.")

        genai.configure(api_key=GEMINI_API_KEY)
        try:
            self.model = genai.GenerativeModel("models/gemini-1.5-flash")  # Replace with actual model name
            logging.info("✅ Gemini model configured successfully.")
        except Exception as e:
            logging.error(f"❌ Error configuring Gemini model: {e}")
            raise

    def generate_chat_response(self, user_message):
        prompt = f"You are an intelligent assistant for a Mini ERP system. Respond helpfully to the following message:\n\nUser: {user_message}\nAssistant:"
        try:
            response = self.model.generate_content(prompt)
            if response.candidates:
                reply = response.candidates[0].content.parts[0].text.strip()
                logging.debug(f"Chatbot response: {reply}")
                return reply
            else:
                logging.warning("❌ No response from Gemini for chatbot.")
                return "I'm sorry, I couldn't process your request at the moment."
        except Exception as e:
            logging.error(f"❌ Error generating chatbot response: {e}")
            return "An error occurred while processing your request."

    def generate_report_summary(self, report_data):
        """
        Generates a natural language summary for a given report.
        report_data: dict containing report details
        """
        prompt = (
            "You are an intelligent report summarizer for a Mini ERP system. "
            "Summarize the following employee performance report concisely and informatively:\n\n"
            f"{report_data}"
        )
        try:
            response = self.model.generate_content(prompt)
            if response.candidates:
                summary = response.candidates[0].content.parts[0].text.strip()
                logging.debug(f"Report Summary: {summary}")
                return summary
            else:
                logging.warning("❌ No response from Gemini for report summary.")
                return "No summary available at this time."
        except Exception as e:
            logging.error(f"❌ Error generating report summary: {e}")
            return "An error occurred while generating the report summary."