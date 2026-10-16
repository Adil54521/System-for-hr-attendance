import os
from dotenv import load_dotenv

# Загрузка переменных из key.env (файл должен быть в корне проекта)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(BASE_DIR, "key.env")
load_dotenv(dotenv_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL")
RECEIVE_URL = os.getenv("RECEIVE_URL")
