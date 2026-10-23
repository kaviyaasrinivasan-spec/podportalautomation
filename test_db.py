import os
from dotenv import load_dotenv
from db_utils import DBHandler

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT", "5432")
}

def test_conn():
    db = DBHandler(**DB_CONFIG)
    conn = db.get_connection()
    if conn:
        print("Successfully connected to the database!")
        conn.close()
    else:
        print("Failed to connect to the database.")

if __name__ == "__main__":
    test_conn()
