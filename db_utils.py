import psycopg2
from psycopg2 import extras
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DBHandler:
    def __init__(self, host, user, password, port, database=None, dbname=None):
        self.conn_params = {
            "host": host,
            "database": database or dbname,
            "user": user,
            "password": password,
            "port": port
        }
    
    def get_connection(self):
        try:
            conn = psycopg2.connect(**self.conn_params)
            return conn
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            return None

    def fetch_pending_uploads(self):
        query = "SELECT id, di_no, seal_invoice, lr_copy, weighment_slip, branch FROM boostentryai.pod_upload WHERE LOWER(client_erp_entry::text) = 'true';"
        conn = self.get_connection()
        if not conn:
            return []
        
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query)
                results = cur.fetchall()
                return results
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return []
        finally:
            conn.close()

    def update_status_to_false(self, row_id):
        query = "UPDATE boostentryai.pod_upload SET client_erp_entry = 'false' WHERE id = %s;"
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            with conn.cursor() as cur:
                cur.execute(query, (row_id,))
                conn.commit()
                logger.info(f"Updated row {row_id} to false.")
                return True
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            return False
        finally:
            conn.close()

    def mark_as_already_existed(self, row_id):
        """Call this when DI is not found in portal — means it's already uploaded/processed."""
        query = "UPDATE boostentryai.pod_upload SET client_erp_entry = 'already existed' WHERE id = %s;"
        conn = self.get_connection()
        if not conn:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(query, (row_id,))
                conn.commit()
                logger.info(f"Row {row_id} marked as 'already existed' in DB.")
                return True
        except Exception as e:
            logger.error(f"Error marking row {row_id} as already existed: {e}")
            return False
        finally:
            conn.close()

    def mark_as_failed(self, row_id):
        """Call this when upload fails or submit success message is not received."""
        query = "UPDATE boostentryai.pod_upload SET client_erp_entry = 'failed' WHERE id = %s;"
        conn = self.get_connection()
        if not conn:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(query, (row_id,))
                conn.commit()
                logger.info(f"Row {row_id} marked as 'failed' in DB.")
                return True
        except Exception as e:
            logger.error(f"Error marking row {row_id} as failed: {e}")
            return False
        finally:
            conn.close()
