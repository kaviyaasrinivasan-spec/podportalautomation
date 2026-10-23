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

def check_paths():
    db = DBHandler(**DB_CONFIG)
    rows = db.fetch_pending_uploads()
    for row in rows:
        print(f"Row {row['id']} Paths:")
        print(f"  Seal: {row['seal_invoice']}")
        print(f"  LR:   {row['lr_copy']}")
        print(f"  WS:   {row['weighment_slip']}")
        print("-" * 20)

if __name__ == "__main__":
    check_paths()
