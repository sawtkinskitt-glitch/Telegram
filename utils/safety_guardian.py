"""
SafetyGuardian - Anti-Ban Protection System
Production-grade rate limiting, FloodWait detection, and ban risk management
"""
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
import os

class SafetyGuardian:
    """Protect accounts from Telegram bans with intelligent rate limiting"""
    
    # Rate limits (configurable)
    HOURLY_LIMIT = 5  # Max clones per hour
    DAILY_LIMIT = 20   # Max clones per day
    FLOODWAIT_COOLDOWN = 86400  # 24 hours in seconds
    MIN_DELAY = 180  # Minimum delay between operations (seconds)
    MAX_DELAY = 320  # Maximum delay (human-like randomization)
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        
    def _get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.db_url)
    
    def check_rate_limit(self, account_id: int) -> Tuple[bool, str, Dict]:
        """
        Check if account can perform clone operation
        Returns: (allowed: bool, reason: str, quota_info: dict)
        """
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check FloodWait status
                cur.execute("""
                    SELECT flood_wait_until FROM telegram_accounts 
                    WHERE id = %s
                """, (account_id,))
                account = cur.fetchone()
                
                if account and account['flood_wait_until']:
                    if datetime.now() < account['flood_wait_until']:
                        remaining = (account['flood_wait_until'] - datetime.now()).total_seconds()
                        return False, f"FloodWait active: {int(remaining/60)} minutes remaining", {}
                
                # Count clones in last hour
                one_hour_ago = datetime.now() - timedelta(hours=1)
                cur.execute("""
                    SELECT COUNT(*) as count FROM clone_attempts 
                    WHERE account_id = %s AND attempted_at > %s
                """, (account_id, one_hour_ago))
                hourly_count = cur.fetchone()['count']
                
                # Count clones in last 24 hours
                one_day_ago = datetime.now() - timedelta(days=1)
                cur.execute("""
                    SELECT COUNT(*) as count FROM clone_attempts 
                    WHERE account_id = %s AND attempted_at > %s
                """, (account_id, one_day_ago))
                daily_count = cur.fetchone()['count']
                
                quota_info = {
                    'hourly_used': hourly_count,
                    'hourly_limit': self.HOURLY_LIMIT,
                    'daily_used': daily_count,
                    'daily_limit': self.DAILY_LIMIT,
                    'hourly_remaining': max(0, self.HOURLY_LIMIT - hourly_count),
                    'daily_remaining': max(0, self.DAILY_LIMIT - daily_count)
                }
                
                # Check hourly limit
                if hourly_count >= self.HOURLY_LIMIT:
                    return False, f"Hourly limit reached ({self.HOURLY_LIMIT}/hour). Try again in 1 hour.", quota_info
                
                # Check daily limit
                if daily_count >= self.DAILY_LIMIT:
                    return False, f"Daily limit reached ({self.DAILY_LIMIT}/day). Try again tomorrow.", quota_info
                
                return True, "OK", quota_info
    
    def calculate_ban_risk(self, account_id: int) -> Tuple[int, str, List[str]]:
        """
        Calculate ban risk score (0-100) based on multiple factors
        Returns: (risk_score: int, risk_level: str, warnings: list)
        """
        risk_score = 0
        warnings = []
        
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Factor 1: Recent FloodWaits (high risk indicator)
                cur.execute("""
                    SELECT COUNT(*) as count FROM flood_wait_events 
                    WHERE account_id = %s AND occurred_at > NOW() - INTERVAL '7 days'
                """, (account_id,))
                recent_floodwaits = cur.fetchone()['count']
                
                if recent_floodwaits > 0:
                    risk_score += min(30, recent_floodwaits * 10)
                    warnings.append(f"{recent_floodwaits} FloodWait(s) in last 7 days")
                
                # Factor 2: Clone frequency
                cur.execute("""
                    SELECT COUNT(*) as count FROM clone_attempts 
                    WHERE account_id = %s AND attempted_at > NOW() - INTERVAL '24 hours'
                """, (account_id,))
                daily_clones = cur.fetchone()['count']
                
                if daily_clones > 15:
                    risk_score += 20
                    warnings.append(f"High activity: {daily_clones} clones in 24h")
                elif daily_clones > 10:
                    risk_score += 10
                    warnings.append(f"Moderate activity: {daily_clones} clones today")
                
                # Factor 3: Failed attempts
                cur.execute("""
                    SELECT COUNT(*) as count FROM clone_attempts 
                    WHERE account_id = %s AND success = FALSE 
                    AND attempted_at > NOW() - INTERVAL '24 hours'
                """, (account_id,))
                failed_attempts = cur.fetchone()['count']
                
                if failed_attempts > 3:
                    risk_score += 25
                    warnings.append(f"{failed_attempts} failed attempts recently")
                
                # Factor 4: Account age and health
                cur.execute("""
                    SELECT created_at, total_clones FROM telegram_accounts 
                    WHERE id = %s
                """, (account_id,))
                account = cur.fetchone()
                
                if account:
                    account_age_days = (datetime.now() - account['created_at']).days
                    if account_age_days < 7:
                        risk_score += 15
                        warnings.append("New account (higher risk)")
                    
                    if account['total_clones'] > 100:
                        risk_score += 10
                        warnings.append(f"High lifetime usage ({account['total_clones']} total clones)")
        
        # Cap at 100
        risk_score = min(100, risk_score)
        
        # Determine risk level
        if risk_score < 30:
            risk_level = "LOW"
        elif risk_score < 60:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"
        
        return risk_score, risk_level, warnings
    
    def get_human_delay(self) -> int:
        """Get randomized human-like delay between operations"""
        return random.randint(self.MIN_DELAY, self.MAX_DELAY)
    
    def record_clone_attempt(self, account_id: int, target_user: str, success: bool, 
                           elements_cloned: List[str], error_message: Optional[str] = None):
        """Record a clone attempt for tracking and analytics"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO clone_attempts 
                    (account_id, target_user, success, elements_cloned, error_message, attempted_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (account_id, target_user, success, elements_cloned, error_message))
                
                # Update account total clones
                if success:
                    cur.execute("""
                        UPDATE telegram_accounts 
                        SET total_clones = total_clones + 1 
                        WHERE id = %s
                    """, (account_id,))
                
                conn.commit()
    
    def record_floodwait(self, account_id: int, wait_seconds: int, operation: str):
        """Record a FloodWait event and set cooldown"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Record event
                cur.execute("""
                    INSERT INTO flood_wait_events 
                    (account_id, wait_seconds, operation, occurred_at)
                    VALUES (%s, %s, %s, NOW())
                """, (account_id, wait_seconds, operation))
                
                # Set FloodWait cooldown on account
                cooldown_until = datetime.now() + timedelta(seconds=self.FLOODWAIT_COOLDOWN)
                cur.execute("""
                    UPDATE telegram_accounts 
                    SET flood_wait_until = %s, flood_wait_count = flood_wait_count + 1
                    WHERE id = %s
                """, (cooldown_until, account_id))
                
                conn.commit()
    
    def get_quota_status(self, account_id: int) -> Dict:
        """Get current rate limit quota status for an account"""
        _, _, quota_info = self.check_rate_limit(account_id)
        risk_score, risk_level, warnings = self.calculate_ban_risk(account_id)
        
        return {
            'quotas': quota_info,
            'risk': {
                'score': risk_score,
                'level': risk_level,
                'warnings': warnings
            },
            'recommended_delay': self.get_human_delay()
        }
    
    def get_clone_history(self, account_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
        """Get clone attempt history"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if account_id:
                    cur.execute("""
                        SELECT ca.*, ta.phone, ta.username 
                        FROM clone_attempts ca
                        JOIN telegram_accounts ta ON ca.account_id = ta.id
                        WHERE ca.account_id = %s
                        ORDER BY ca.attempted_at DESC 
                        LIMIT %s
                    """, (account_id, limit))
                else:
                    cur.execute("""
                        SELECT ca.*, ta.phone, ta.username 
                        FROM clone_attempts ca
                        JOIN telegram_accounts ta ON ca.account_id = ta.id
                        ORDER BY ca.attempted_at DESC 
                        LIMIT %s
                    """, (limit,))
                
                return [dict(row) for row in cur.fetchall()]
    
    def get_floodwait_status(self, account_id: int) -> Optional[Dict]:
        """Get FloodWait status for an account"""
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT flood_wait_until, flood_wait_count 
                    FROM telegram_accounts 
                    WHERE id = %s
                """, (account_id,))
                account = cur.fetchone()
                
                if not account or not account['flood_wait_until']:
                    return None
                
                if datetime.now() >= account['flood_wait_until']:
                    # Cooldown expired, clear it
                    cur.execute("""
                        UPDATE telegram_accounts 
                        SET flood_wait_until = NULL 
                        WHERE id = %s
                    """, (account_id,))
                    conn.commit()
                    return None
                
                remaining = (account['flood_wait_until'] - datetime.now()).total_seconds()
                return {
                    'active': True,
                    'expires_at': account['flood_wait_until'].isoformat(),
                    'remaining_seconds': int(remaining),
                    'total_floodwaits': account['flood_wait_count']
                }

# Singleton instance
guardian = SafetyGuardian()
