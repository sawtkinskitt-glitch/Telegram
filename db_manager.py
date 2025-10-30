import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required for PostgreSQL access")

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
                total_clones INTEGER DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS account_risk_history (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                ban_risk_score INTEGER NOT NULL,
                snapshot_date DATE NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE,
                UNIQUE (account_id, snapshot_date)
            )
        """)

        cursor.execute("""ALTER TABLE telegram_accounts
                          ADD COLUMN IF NOT EXISTS total_clones INTEGER DEFAULT 0""")
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_flood_wait_account ON flood_wait_events(account_id, occurred_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_clone_attempts_account ON clone_attempts(account_id, attempted_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_profile_changes_account ON profile_changes(account_id, changed_at)
        """)
        
        # Create distributed lock table for preventing AUTH_KEY_DUPLICATED
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_session_locks (
                id SERIAL PRIMARY KEY,
                account_id INTEGER UNIQUE NOT NULL,
                locked_by INTEGER NOT NULL,
                locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
            )
        """)
        
        # Create index for faster stale lock cleanup
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_locks_locked_at 
            ON telegram_session_locks(locked_at)
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
    def get_primary_account():
        """Return the account marked as primary"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM telegram_accounts
                WHERE is_primary = TRUE
                ORDER BY last_active DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            cursor.close()
        if row:
            return AccountManager.get_account_by_id(row[0])
        return None

    @staticmethod
    def get_recent_account():
        """Return the most recently active account (prefers active ones)"""
        account_id = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM telegram_accounts
                WHERE is_active = TRUE
                ORDER BY last_active DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                account_id = row[0]
            else:
                cursor.execute(
                    """
                    SELECT id FROM telegram_accounts
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                account_id = row[0] if row else None
            cursor.close()
        if account_id:
            return AccountManager.get_account_by_id(account_id)
        return None

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

    @staticmethod
    def delete_account_by_id(account_id):
        """Delete account by database ID"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telegram_accounts WHERE id = %s", (account_id,))
            cursor.close()

    @staticmethod
    def clear_account_session(account_id, status="auth_error"):
        """Clear stored session data for an account and mark inactive"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE telegram_accounts
                SET session_encrypted = NULL,
                    last_active = CURRENT_TIMESTAMP,
                    account_status = %s,
                    is_active = FALSE
                WHERE id = %s
                """,
                (status, account_id),
            )
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

            floodwait_events = []
            if recent_floodwaits:
                for row in recent_floodwaits:
                    event = dict(row)
                    if 'wait_duration' in event:
                        event['wait_seconds'] = event.pop('wait_duration')
                    if 'operation_type' in event:
                        event['operation'] = event.pop('operation_type')
                    floodwait_events.append(event)
            
            return {
                'metrics': dict(metrics) if metrics else None,
                'clone_stats': dict(clone_stats) if clone_stats else {'total': 0, 'successful': 0},
                'recent_floodwaits': floodwait_events,
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

            serialized = []
            for row in events:
                event = dict(row)
                if 'wait_duration' in event:
                    event['wait_seconds'] = event.pop('wait_duration')
                if 'operation_type' in event:
                    event['operation'] = event.pop('operation_type')
                serialized.append(event)
            return serialized
    
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

            cursor.execute("""
                INSERT INTO account_risk_history (account_id, ban_risk_score, snapshot_date)
                VALUES (%s, %s, CURRENT_DATE)
                ON CONFLICT (account_id, snapshot_date) DO UPDATE
                SET ban_risk_score = EXCLUDED.ban_risk_score,
                    recorded_at = CURRENT_TIMESTAMP
            """, (account_id, ban_risk_score))
            cursor.close()


class AnalyticsManager:
    """Provide aggregated analytics for dashboards and sparklines"""

    @staticmethod
    def _generate_hour_buckets(hours: int):
        end = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        return [end - timedelta(hours=i) for i in reversed(range(hours))]

    @staticmethod
    def _generate_day_buckets(days: int):
        end = datetime.utcnow().date()
        return [end - timedelta(days=i) for i in reversed(range(days))]

    @staticmethod
    def get_accounts_activity(hours: int = 24):
        """Return per-account clone and FloodWait counts grouped hourly"""
        interval = f"{hours} hours"
        buckets = AnalyticsManager._generate_hour_buckets(hours)

        with get_db_connection() as conn:
            accounts_cursor = conn.cursor()
            accounts_cursor.execute("SELECT id FROM telegram_accounts")
            account_rows = accounts_cursor.fetchall()
            accounts_cursor.close()

            clone_cursor = conn.cursor()
            clone_cursor.execute(
                """
                SELECT account_id, date_trunc('hour', attempted_at) AS bucket, COUNT(*)
                FROM clone_attempts
                WHERE attempted_at >= NOW() - INTERVAL %s
                GROUP BY account_id, bucket
                """,
                (interval,),
            )
            clone_rows = clone_cursor.fetchall()
            clone_cursor.close()

            flood_cursor = conn.cursor()
            flood_cursor.execute(
                """
                SELECT account_id, date_trunc('hour', occurred_at) AS bucket, COUNT(*)
                FROM flood_wait_events
                WHERE occurred_at >= NOW() - INTERVAL %s
                GROUP BY account_id, bucket
                """,
                (interval,),
            )
            flood_rows = flood_cursor.fetchall()
            flood_cursor.close()

        clone_map = defaultdict(dict)
        for account_id, bucket, count in clone_rows:
            clone_map[account_id][bucket.replace(minute=0, second=0, microsecond=0)] = count

        flood_map = defaultdict(dict)
        for account_id, bucket, count in flood_rows:
            flood_map[account_id][bucket.replace(minute=0, second=0, microsecond=0)] = count

        account_ids = [row[0] for row in account_rows]
        activity = {}
        for account_id in account_ids:
            clones_series = []
            floods_series = []
            for bucket in buckets:
                clones_series.append({
                    "timestamp": bucket.isoformat() + "Z",
                    "count": clone_map[account_id].get(bucket, 0),
                })
                floods_series.append({
                    "timestamp": bucket.isoformat() + "Z",
                    "count": flood_map[account_id].get(bucket, 0),
                })
            activity[str(account_id)] = {
                "clones": clones_series,
                "flood_waits": floods_series,
            }

        return {
            "hours": hours,
            "activity": activity,
        }

    @staticmethod
    def get_global_timeseries(hours: int = 24, days: int = 7):
        """Return aggregated timeseries for dashboard sparklines"""
        hours_interval = f"{hours} hours"
        clones_buckets = AnalyticsManager._generate_hour_buckets(hours)
        days_buckets = AnalyticsManager._generate_day_buckets(days)

        with get_db_connection() as conn:
            clone_cursor = conn.cursor()
            clone_cursor.execute(
                """
                SELECT date_trunc('hour', attempted_at) AS bucket, COUNT(*)
                FROM clone_attempts
                WHERE attempted_at >= NOW() - INTERVAL %s
                GROUP BY bucket
                """,
                (hours_interval,),
            )
            clone_rows = clone_cursor.fetchall()
            clone_cursor.close()

            flood_cursor = conn.cursor()
            flood_cursor.execute(
                """
                SELECT date_trunc('hour', occurred_at) AS bucket, COUNT(*)
                FROM flood_wait_events
                WHERE occurred_at >= NOW() - INTERVAL %s
                GROUP BY bucket
                """,
                (hours_interval,),
            )
            flood_rows = flood_cursor.fetchall()
            flood_cursor.close()

            risk_cursor = conn.cursor()
            risk_cursor.execute(
                """
                SELECT snapshot_date, AVG(ban_risk_score)::numeric(10,2)
                FROM account_risk_history
                WHERE snapshot_date >= CURRENT_DATE - %s::integer
                GROUP BY snapshot_date
                """,
                (days,),
            )
            risk_rows = risk_cursor.fetchall()
            risk_cursor.close()

        clone_series_map = {bucket.replace(minute=0, second=0, microsecond=0): count for bucket, count in clone_rows}
        flood_series_map = {bucket.replace(minute=0, second=0, microsecond=0): count for bucket, count in flood_rows}
        risk_series_map = {snapshot: float(score) for snapshot, score in risk_rows}

        clones_series = [
            {"timestamp": bucket.isoformat() + "Z", "count": clone_series_map.get(bucket, 0)}
            for bucket in clones_buckets
        ]

        floods_series = [
            {"timestamp": bucket.isoformat() + "Z", "count": flood_series_map.get(bucket, 0)}
            for bucket in clones_buckets
        ]

        risk_series = [
            {"date": bucket.isoformat(), "score": risk_series_map.get(bucket, 0.0)}
            for bucket in days_buckets
        ]

        return {
            "clones_last_hours": clones_series,
            "floodwaits_last_hours": floods_series,
            "ban_risk_daily": risk_series,
        }

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
