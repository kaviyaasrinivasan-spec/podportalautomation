import os
from dotenv import load_dotenv
from db_utils import DBHandler

load_dotenv()

_base = {"host": os.getenv("DB_HOST"), "password": os.getenv("DB_PASSWORD"), "port": os.getenv("DB_PORT", "5432")}

# Try different combinations
CONFIGS = [
    {**_base, "database": os.getenv("DB_NAME"), "user": os.getenv("DB_USER")},
    {**_base, "database": os.getenv("DB_NAME"), "user": os.getenv("DB_USER", "").capitalize()},
    {**_base, "database": "postgres", "user": os.getenv("DB_USER")},
]

def test_conn():
    for i, config in enumerate(CONFIGS):
        print(f"Testing config {i}...")
        db = DBHandler(**config)
        conn = db.get_connection()
        if conn:
            print(f"Successfully connected with config {i}!")
            conn.close()
            return
        else:
            print(f"Failed config {i}.")

if __name__ == "__main__":
    test_conn()
