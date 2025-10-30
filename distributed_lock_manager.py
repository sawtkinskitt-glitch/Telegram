"""
Distributed Session Lock Manager for Telegram Authentication

Prevents AUTH_KEY_DUPLICATED by ensuring only one container
can connect to Telegram with a given session at any time.

Uses PostgreSQL as distributed lock coordinator with:
- Automatic stale lock cleanup
- Heartbeat mechanism
- Graceful lock release
"""
import os
import time
import logging
from contextlib import contextmanager
from db_manager import get_db_connection

logger = logging.getLogger(__name__)


class DistributedLockManager:
    """Manages distributed locks for Telegram sessions across containers"""
    
    def __init__(self, account_id):
        self.account_id = account_id
        self.locked_by = os.getpid()
        self.is_locked = False
        self.lock_acquired_at = None
        
    def acquire_lock(self, timeout=30):
        """
        Acquire exclusive lock for Telegram session.
        
        Args:
            timeout: Maximum seconds to wait for lock acquisition
            
        Returns:
            bool: True if lock acquired, False otherwise
        """
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time < timeout:
            attempt += 1
            
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Clean up stale locks (older than 5 minutes)
                    cursor.execute("""
                        DELETE FROM telegram_session_locks 
                        WHERE locked_at < NOW() - INTERVAL '5 minutes'
                    """)
                    stale_count = cursor.rowcount
                    if stale_count > 0:
                        logger.info(f"🧹 Cleaned up {stale_count} stale lock(s)")
                    
                    # Try to acquire lock
                    cursor.execute("""
                        INSERT INTO telegram_session_locks (account_id, locked_by, locked_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (account_id) DO NOTHING
                        RETURNING id
                    """, (self.account_id, self.locked_by))
                    
                    result = cursor.fetchone()
                    cursor.close()
                    
                    if result:
                        self.is_locked = True
                        self.lock_acquired_at = time.time()
                        logger.info(f"🔒 Acquired Telegram lock for account {self.account_id} (PID: {self.locked_by}, attempt {attempt})")
                        return True
                    
                    # Check who holds the lock
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT locked_by, locked_at 
                        FROM telegram_session_locks
                        WHERE account_id = %s
                    """, (self.account_id,))
                    
                    lock_info = cursor.fetchone()
                    cursor.close()
                    
                    if lock_info:
                        other_pid, locked_at = lock_info
                        logger.debug(f"⏳ Lock held by PID {other_pid} since {locked_at} (attempt {attempt}/{int(timeout)})")
                    
            except Exception as e:
                logger.error(f"❌ Lock acquisition error (attempt {attempt}): {e}")
            
            # Wait before retry
            if time.time() - start_time < timeout:
                time.sleep(1)
        
        logger.error(f"❌ Failed to acquire lock for account {self.account_id} after {timeout}s")
        return False
    
    def release_lock(self):
        """Release the distributed lock"""
        if not self.is_locked:
            logger.debug("No lock to release")
            return True
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM telegram_session_locks
                    WHERE account_id = %s AND locked_by = %s
                """, (self.account_id, self.locked_by))
                
                deleted = cursor.rowcount
                cursor.close()
                
                if deleted > 0:
                    self.is_locked = False
                    lock_duration = time.time() - self.lock_acquired_at if self.lock_acquired_at else 0
                    logger.info(f"🔓 Released Telegram lock for account {self.account_id} (held for {lock_duration:.1f}s)")
                    return True
                else:
                    logger.warning(f"⚠️  Lock for account {self.account_id} was not held by PID {self.locked_by}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Lock release error: {e}")
            return False
    
    def update_heartbeat(self):
        """Update lock timestamp to show this instance is still alive"""
        if not self.is_locked:
            return False
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE telegram_session_locks 
                    SET locked_at = NOW()
                    WHERE account_id = %s AND locked_by = %s
                """, (self.account_id, self.locked_by))
                
                updated = cursor.rowcount
                cursor.close()
                
                if updated > 0:
                    logger.debug(f"💓 Heartbeat updated for account {self.account_id}")
                    return True
                else:
                    logger.warning(f"⚠️  Lost lock for account {self.account_id}")
                    self.is_locked = False
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Heartbeat error: {e}")
            return False
    
    @contextmanager
    def lock_context(self, timeout=30):
        """
        Context manager for automatic lock acquisition and release.
        
        Usage:
            with lock_manager.lock_context(timeout=30):
                # Your code here
                # Lock automatically released on exit
        """
        acquired = self.acquire_lock(timeout=timeout)
        if not acquired:
            raise RuntimeError(f"Could not acquire lock for account {self.account_id}")
        
        try:
            yield self
        finally:
            self.release_lock()


def ensure_lock_table_exists():
    """Ensure the telegram_session_locks table exists in the database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telegram_session_locks (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER UNIQUE NOT NULL,
                    locked_by INTEGER NOT NULL,
                    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES telegram_accounts(id) ON DELETE CASCADE
                )
            """)
            
            # Create index for faster cleanup queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_locks_locked_at 
                ON telegram_session_locks(locked_at)
            """)
            
            cursor.close()
            logger.info("✅ Distributed lock table initialized")
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize lock table: {e}")
        return False
