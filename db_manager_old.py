import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from datetime import datetime
import json

DATABASE_URL = os.getenv('DATABASE_URL')

@contextmanager
def get_db_connection():
    """Get database connection with context manager"""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_database():
    """Initialize database schema - works with existing schema"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clone_attempts (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                target_user_id BIGINT NOT NULL,
                success BOOLEAN NOT NULL,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profile_changes (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                change_type VARCHAR(50) NOT NULL,
                previous_value TEXT,
                new_value TEXT,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS safety_metrics (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL UNIQUE,
                ban_risk_score INTEGER NOT NULL,
                clones_last_hour INTEGER DEFAULT 0,
                clones_last_day INTEGER DEFAULT 0,
                profile_changes_last_day INTEGER DEFAULT 0,
                last_flood_wait TIMESTAMP,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_flood_wait_account ON flood_wait_events(account_id, occurred_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_clone_attempts_account ON clone_attempts(account_id, attempted_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_profile_changes_account ON profile_changes(account_id, changed_at)
        """)
        
        conn.commit()
        cursor.close()

class AccountManager:
    """Manage Telegram accounts in database"""
    
    @staticmethod
    def add_account(phone, session_encrypted, first_name=None, last_name=None, username=None):
        """Add new Telegram account"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO telegram_accounts 
                (phone_number, session_encrypted, first_name, last_name, username)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (phone_number) DO UPDATE
                SET session_encrypted = EXCLUDED.session_encrypted,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (phone, session_encrypted, first_name, last_name, username))
            result = cursor.fetchone()
            cursor.close()
            return result[0]
    
    @staticmethod
    def get_all_accounts():
        """Get all accounts with health metrics"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT 
                    ta.*,
                    sm.ban_risk_score,
                    sm.clones_last_hour,
                    sm.clones_last_day,
                    (SELECT COUNT(*) FROM flood_wait_events WHERE phone_number = ta.phone_number 
                     AND resolved_at IS NULL) as active_floodwaits
                FROM telegram_accounts ta
                LEFT JOIN safety_metrics sm ON ta.phone_number = sm.phone_number
                ORDER BY ta.created_at DESC
            """)
            accounts = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in accounts]
    
    @staticmethod
    def get_account(phone):
        """Get single account details"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM telegram_accounts WHERE phone_number = %s
            """, (phone,))
            account = cursor.fetchone()
            cursor.close()
            return dict(account) if account else None
    
    @staticmethod
    def update_account_status(phone, status, last_seen=None):
        """Update account status"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if last_seen:
                cursor.execute("""
                    UPDATE telegram_accounts 
                    SET status = %s, last_seen = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE phone_number = %s
                """, (status, last_seen, phone))
            else:
                cursor.execute("""
                    UPDATE telegram_accounts 
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE phone_number = %s
                """, (status, phone))
            cursor.close()
    
    @staticmethod
    def delete_account(phone):
        """Delete account (cascades to all related records)"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telegram_accounts WHERE phone_number = %s", (phone,))
            cursor.close()

class SafetyMetricsManager:
    """Manage safety metrics and reports"""
    
    @staticmethod
    def get_safety_report(phone):
        """Get comprehensive safety report for account"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM safety_metrics 
                WHERE phone_number = %s 
                ORDER BY calculated_at DESC LIMIT 1
            """, (phone,))
            metrics = cursor.fetchone()
            
            cursor.execute("""
                SELECT COUNT(*) as total, 
                       COUNT(CASE WHEN success THEN 1 END) as successful
                FROM clone_attempts 
                WHERE phone_number = %s 
                AND attempted_at > NOW() - INTERVAL '24 hours'
            """, (phone,))
            clone_stats = cursor.fetchone()
            
            cursor.execute("""
                SELECT * FROM flood_wait_events 
                WHERE phone_number = %s 
                ORDER BY triggered_at DESC LIMIT 10
            """, (phone,))
            recent_floodwaits = cursor.fetchall()
            
            cursor.execute("""
                SELECT COUNT(*) as count FROM profile_changes 
                WHERE phone_number = %s 
                AND changed_at > NOW() - INTERVAL '24 hours'
            """, (phone,))
            profile_changes_24h = cursor.fetchone()
            
            cursor.close()
            
            return {
                'metrics': dict(metrics) if metrics else None,
                'clone_stats': dict(clone_stats) if clone_stats else {'total': 0, 'successful': 0},
                'recent_floodwaits': [dict(row) for row in recent_floodwaits] if recent_floodwaits else [],
                'profile_changes_24h': dict(profile_changes_24h)['count'] if profile_changes_24h else 0
            }
    
    @staticmethod
    def get_active_floodwaits(phone):
        """Get active FloodWait events"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT * FROM flood_wait_events 
                WHERE phone_number = %s AND resolved_at IS NULL
                ORDER BY triggered_at DESC
            """, (phone,))
            events = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in events]

if __name__ == '__main__':
    print("Initializing database schema...")
    init_database()
    print("✅ Database schema initialized successfully!")
