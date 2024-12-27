# app/config.py

import os
import logging
from logging.handlers import RotatingFileHandler
import sys

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret_key")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    
    # Logging Configuration
    LOG_TO_STDOUT = os.getenv("LOG_TO_STDOUT")
    LOG_LEVEL = logging.DEBUG if FLASK_ENV == "development" else logging.INFO

    @staticmethod
    def init_app(app):
        if not os.path.exists("logs"):
            os.makedirs("logs")
        if Config.LOG_TO_STDOUT:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(Config.LOG_LEVEL)
            formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
            stream_handler.setFormatter(formatter)
            app.logger.addHandler(stream_handler)
        else:
            file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
            file_handler.setLevel(Config.LOG_LEVEL)
            formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
            file_handler.setFormatter(formatter)
            app.logger.addHandler(file_handler)
        
        app.logger.setLevel(Config.LOG_LEVEL)
        app.logger.info('Student Management System startup')