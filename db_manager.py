import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from datetime import datetime

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
            CREATE TABLE IF NOT EXISTS telegram_accounts (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) UNIQUE NOT NULL,
                session_encrypted TEXT NOT NULL,
                api_id VARCHAR(50),
                api_hash_encrypted TEXT,
                name VARCHAR(255),
                username VARCHAR(255),
                first_name VARCHAR(255),
                profile_photo_url TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                is_primary BOOLEAN DEFAULT FALSE,
                account_status VARCHAR(50) DEFAULT 'active',
                flood_wait_until TIMESTAMP,
                flood_wait_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account_health (
                id SERIAL PRIMARY KEY,
                account_id INTEGER UNIQUE NOT NULL,
                ban_risk_score INTEGER DEFAULT 0,
                flood_wait_count INTEGER DEFAULT 0,
                last_flood_wait TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flood_wait_events (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                wait_duration INTEGER NOT NULL,
                operation_type VARCHAR(50),
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clone_attempts (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                target_user VARCHAR(255) NOT NULL,
                target_user_id BIGINT,
                success BOOLEAN NOT NULL,
                elements_cloned TEXT,
                error_message TEXT,
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
    """Manage Telegram accounts - aligned with existing schema"""
    
    @staticmethod
    def _get_account_id(conn, phone):
        """Helper to get account_id from phone"""
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM telegram_accounts WHERE phone = %s", (phone,))
        result = cursor.fetchone()
        cursor.close()
        return result[0] if result else None
    
    @staticmethod
    def add_account(phone, session_encrypted, name=None, api_id=None, api_hash_encrypted=None, username=None, first_name=None, profile_photo_url=None):
        """Add or update Telegram account"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO telegram_accounts 
                (phone, session_encrypted, name, api_id, api_hash_encrypted, username, first_name, profile_photo_url, is_active, created_at, last_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (phone) DO UPDATE
                SET session_encrypted = EXCLUDED.session_encrypted,
                    name = COALESCE(EXCLUDED.name, telegram_accounts.name),
                    api_id = COALESCE(EXCLUDED.api_id, telegram_accounts.api_id),
                    api_hash_encrypted = COALESCE(EXCLUDED.api_hash_encrypted, telegram_accounts.api_hash_encrypted),
                    username = COALESCE(EXCLUDED.username, telegram_accounts.username),
                    first_name = COALESCE(EXCLUDED.first_name, telegram_accounts.first_name),
                    profile_photo_url = COALESCE(EXCLUDED.profile_photo_url, telegram_accounts.profile_photo_url),
                    last_active = CURRENT_TIMESTAMP
                RETURNING id
            """, (phone, session_encrypted, name, api_id, api_hash_encrypted, username, first_name, profile_photo_url))
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else None
    
    @staticmethod
    def get_all_accounts():
        """Get all accounts with safety metrics"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT 
                    ta.*,
                    ah.ban_risk_score as health_ban_risk,
                    ah.flood_wait_count,
                    ah.updated_at as health_last_check,
                    sm.ban_risk_score,
                    sm.clones_last_hour,
                    sm.clones_last_day,
                    sm.calculated_at as metrics_updated,
                    (SELECT COUNT(*) FROM flood_wait_events fwe 
                     WHERE fwe.account_id = ta.id 
                     AND fwe.occurred_at > NOW() - INTERVAL '24 hours') as recent_floodwaits
                FROM telegram_accounts ta
                LEFT JOIN account_health ah ON ta.id = ah.account_id
                LEFT JOIN safety_metrics sm ON ta.id = sm.account_id
                ORDER BY ta.created_at DESC
            """)
            accounts = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in accounts]
    
    @staticmethod
    def get_account_by_phone(phone):
        """Get account details by phone"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT ta.*, sm.ban_risk_score, sm.clones_last_hour, sm.clones_last_day
                FROM telegram_accounts ta
                LEFT JOIN safety_metrics sm ON ta.id = sm.account_id
                WHERE ta.phone = %s
            """, (phone,))
            account = cursor.fetchone()
            cursor.close()
            return dict(account) if account else None
    
    @staticmethod
    def get_account_by_id(account_id):
        """Get account details by ID"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT ta.*, sm.ban_risk_score
                FROM telegram_accounts ta
                LEFT JOIN safety_metrics sm ON ta.id = sm.account_id
                WHERE ta.id = %s
            """, (account_id,))
            account = cursor.fetchone()
            cursor.close()
            return dict(account) if account else None
    
    @staticmethod
    def update_account_status(phone, status, last_active=None):
        """Update account status using existing schema columns"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if last_active:
                cursor.execute("""
                    UPDATE telegram_accounts 
                    SET account_status = %s, last_active = %s
                    WHERE phone = %s
                """, (status, last_active, phone))
            else:
                cursor.execute("""
                    UPDATE telegram_accounts 
                    SET account_status = %s, last_active = CURRENT_TIMESTAMP
                    WHERE phone = %s
                """, (status, phone))
            cursor.close()
    
    @staticmethod
    def delete_account(phone):
        """Delete account (cascades to all related records)"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telegram_accounts WHERE phone = %s", (phone,))
            cursor.close()

class SafetyMetricsManager:
    """Manage safety metrics and reports - aligned with existing schema"""
    
    @staticmethod
    def get_safety_report(phone):
        """Get comprehensive safety report for account"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            account_id = AccountManager._get_account_id(conn, phone)
            if not account_id:
                return None
            
            cursor.execute("""
                SELECT * FROM safety_metrics 
                WHERE account_id = %s 
                ORDER BY calculated_at DESC LIMIT 1
            """, (account_id,))
            metrics = cursor.fetchone()
            
            cursor.execute("""
                SELECT COUNT(*) as total, 
                       COUNT(CASE WHEN success THEN 1 END) as successful
                FROM clone_attempts 
                WHERE account_id = %s 
                AND attempted_at > NOW() - INTERVAL '24 hours'
            """, (account_id,))
            clone_stats = cursor.fetchone()
            
            cursor.execute("""
                SELECT * FROM flood_wait_events 
                WHERE account_id = %s 
                ORDER BY occurred_at DESC LIMIT 10
            """, (account_id,))
            recent_floodwaits = cursor.fetchall()
            
            cursor.execute("""
                SELECT COUNT(*) as count FROM profile_changes 
                WHERE account_id = %s 
                AND changed_at > NOW() - INTERVAL '24 hours'
            """, (account_id,))
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
        """Get recent FloodWait events (last 24h)"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            account_id = AccountManager._get_account_id(conn, phone)
            if not account_id:
                return []
            
            cursor.execute("""
                SELECT * FROM flood_wait_events 
                WHERE account_id = %s 
                AND occurred_at > NOW() - INTERVAL '24 hours'
                ORDER BY occurred_at DESC
            """, (account_id,))
            events = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in events]
    
    @staticmethod
    def upsert_safety_metrics(account_id, ban_risk_score, clones_last_hour, clones_last_day, profile_changes_last_day, last_flood_wait=None):
        """Insert or update safety metrics for an account"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO safety_metrics 
                (account_id, ban_risk_score, clones_last_hour, clones_last_day, profile_changes_last_day, last_flood_wait, calculated_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (account_id) DO UPDATE
                SET ban_risk_score = EXCLUDED.ban_risk_score,
                    clones_last_hour = EXCLUDED.clones_last_hour,
                    clones_last_day = EXCLUDED.clones_last_day,
                    profile_changes_last_day = EXCLUDED.profile_changes_last_day,
                    last_flood_wait = EXCLUDED.last_flood_wait,
                    calculated_at = CURRENT_TIMESTAMP
            """, (account_id, ban_risk_score, clones_last_hour, clones_last_day, profile_changes_last_day, last_flood_wait))
            cursor.close()

if __name__ == '__main__':
    print("Initializing database schema...")
    init_database()
    print("✅ Database schema initialized successfully!")
    
    print("\nTesting managers...")
    try:
        accounts = AccountManager.get_all_accounts()
        print(f"✅ Found {len(accounts)} accounts")
        for acc in accounts:
            print(f"  - {acc.get('phone')}: {acc.get('account_status', 'active')}")
    except Exception as e:
        print(f"❌ Error: {e}")
