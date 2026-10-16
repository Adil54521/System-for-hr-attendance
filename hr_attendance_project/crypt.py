from cryptography.fernet import Fernet
from dotenv import load_dotenv
import os

path_env = os.path.join("C:\\HR\hr_attendance_project", ".env")

key = Fernet.generate_key()
cipher = Fernet(key)
content = ""

with open("gemini_key.txt", "r", encoding="utf-8") as file:
    content = file.read()
    data = load_dotenv(path_env)
    print(data)
    encrypted = cipher.encrypt(data.encode())
    
if content != "":
    with open(".env", "w",  encoding="utf-8") as file:
        encrypted = file.write(content)
        print(encrypted)