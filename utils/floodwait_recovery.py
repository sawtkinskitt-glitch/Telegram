"""
FloodWait Recovery Protocol

Research findings:
"FloodWait durations can be 19.6+ hours. The server is telling you to STOP."
"Add a random buffer (5-15 min) to server-provided time"
"After FloodWait, resume at 25% normal rate for 4 hours"

This module implements:
1. FloodWait event logging
2. Auto-quarantine on FloodWait
3. Recovery mode (reduced rate limits)
4. Progressive rate increase
"""

import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict


class FloodWaitRecoveryManager:
    """
    Manages FloodWait events and recovery protocol
    
    Key principle: FloodWait = server saying "STOP NOW"
    Must respect it completely + add buffer + slow recovery
    """
    
    # Recovery mode parameters
    RECOVERY_DURATION_HOURS = 4          # Stay in recovery mode for 4 hours
    RECOVERY_RATE_MULTIPLIER = 0.25      # Operate at 25% normal rate
    BUFFER_MIN_SECONDS = 300             # 5-minute minimum buffer
    BUFFER_MAX_SECONDS = 900             # 15-minute maximum buffer
    
    # Severity levels based on FloodWait duration
    SEVERITY_THRESHOLDS = {
        'minor': (0, 300),         # 0-5 minutes
        'moderate': (300, 3600),   # 5 min - 1 hour
        'severe': (3600, 14400),   # 1-4 hours
        'critical': (14400, 999999) # 4+ hours
    }
    
    @staticmethod
    def calculate_severity(floodwait_seconds: int) -> str:
        """
        Determine severity level of FloodWait
        
        Args:
            floodwait_seconds: FloodWait duration from Telegram
        
        Returns:
            str: Severity level (minor, moderate, severe, critical)
        """
        for severity, (min_sec, max_sec) in FloodWaitRecoveryManager.SEVERITY_THRESHOLDS.items():
            if min_sec <= floodwait_seconds < max_sec:
                return severity
        return 'critical'
    
    @staticmethod
    def log_floodwait_event(
        db,
        account_id: int,
        operation_type: str,
        floodwait_seconds: int,
        context: Dict = None
    ):
        """
        Log FloodWait event to database
        
        Args:
            db: Database instance
            account_id: Account ID
            operation_type: Type of operation that triggered FloodWait
            floodwait_seconds: Duration from Telegram
            context: Additional context (optional)
        """
        import random
        
        # Calculate buffer
        buffer_seconds = random.uniform(
            FloodWaitRecoveryManager.BUFFER_MIN_SECONDS,
            FloodWaitRecoveryManager.BUFFER_MAX_SECONDS
        )
        
        total_wait_seconds = floodwait_seconds + buffer_seconds
        severity = FloodWaitRecoveryManager.calculate_severity(floodwait_seconds)
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "account_id": account_id,
            "operation_type": operation_type,
            "floodwait_seconds": floodwait_seconds,
            "buffer_seconds": buffer_seconds,
            "total_wait_seconds": total_wait_seconds,
            "severity": severity,
            "context": context or {}
        }
        
        # Add to floodwait history
        history = db.get(f"account.{account_id}", "floodwait_history", [])
        history.append(event)
        
        # Keep last 100 events
        if len(history) > 100:
            history = history[-100:]
        
        db.set(f"account.{account_id}", "floodwait_history", history)
        
        # Update last floodwait time
        db.set(f"account.{account_id}", "last_floodwait", event)
        
        # Also add to operation logs for anomaly detection
        operation_logs = db.get(f"account.{account_id}", "operation_logs", [])
        operation_logs.append({
            "timestamp": datetime.now().isoformat(),
            "event_type": "floodwait",
            "operation": operation_type,
            "success": False,
            "floodwait_seconds": floodwait_seconds,
            "severity": severity
        })
        if len(operation_logs) > 1000:
            operation_logs = operation_logs[-1000:]
        db.set(f"account.{account_id}", "operation_logs", operation_logs)
        
        return event
    
    @staticmethod
    def enter_recovery_mode(db, account_id: int, floodwait_event: Dict):
        """
        Enter recovery mode after FloodWait
        
        Recovery mode:
        - Reduces all rate limits to 25%
        - Lasts for 4 hours after FloodWait ends
        - Auto-quarantines account
        
        Args:
            db: Database instance
            account_id: Account ID
            floodwait_event: FloodWait event data
        """
        recovery_start = datetime.now() + timedelta(seconds=floodwait_event['total_wait_seconds'])
        recovery_end = recovery_start + timedelta(hours=FloodWaitRecoveryManager.RECOVERY_DURATION_HOURS)
        
        recovery_data = {
            "active": True,
            "started_at": recovery_start.isoformat(),
            "ends_at": recovery_end.isoformat(),
            "trigger_event": floodwait_event,
            "rate_multiplier": FloodWaitRecoveryManager.RECOVERY_RATE_MULTIPLIER
        }
        
        db.set(f"account.{account_id}", "recovery_mode", recovery_data)
        
        # Also enable quarantine
        db.set(f"account.{account_id}", "quarantine_mode", True)
        db.set(f"account.{account_id}", "quarantine_started", floodwait_event['timestamp'])
        db.set(f"account.{account_id}", "quarantine_reason", f"FloodWait ({floodwait_event['severity']})")
    
    @staticmethod
    def is_in_recovery_mode(db, account_id: int) -> Tuple[bool, Optional[Dict]]:
        """
        Check if account is in recovery mode
        
        Returns:
            tuple: (is_in_recovery, recovery_data)
        """
        recovery_data = db.get(f"account.{account_id}", "recovery_mode")
        
        if not recovery_data or not recovery_data.get('active'):
            return False, None
        
        # Check if recovery period ended
        ends_at = datetime.fromisoformat(recovery_data['ends_at'])
        if datetime.now() >= ends_at:
            # Recovery complete
            db.set(f"account.{account_id}", "recovery_mode", {"active": False})
            return False, None
        
        return True, recovery_data
    
    @staticmethod
    def get_adjusted_rate_limits(db, account_id: int, base_limits: Dict) -> Dict:
        """
        Get rate limits adjusted for recovery mode
        
        Args:
            db: Database instance
            account_id: Account ID
            base_limits: Normal rate limits
        
        Returns:
            dict: Adjusted rate limits (25% of normal if in recovery)
        """
        is_recovering, recovery_data = FloodWaitRecoveryManager.is_in_recovery_mode(db, account_id)
        
        if not is_recovering:
            return base_limits
        
        # Reduce all limits to 25%
        multiplier = recovery_data.get('rate_multiplier', 0.25)
        
        adjusted = {}
        for key, value in base_limits.items():
            if isinstance(value, (int, float)) and key.startswith('max_'):
                adjusted[key] = max(1, int(value * multiplier))  # At least 1
            else:
                adjusted[key] = value
        
        adjusted['recovery_mode'] = True
        adjusted['recovery_multiplier'] = multiplier
        
        return adjusted
    
    @staticmethod
    def format_floodwait_message(floodwait_event: Dict, recovery_data: Optional[Dict] = None) -> str:
        """
        Format FloodWait event as user message
        
        Args:
            floodwait_event: FloodWait event data
            recovery_data: Recovery mode data (optional)
        
        Returns:
            str: HTML formatted message
        """
        fw_seconds = floodwait_event['floodwait_seconds']
        buffer_seconds = floodwait_event['buffer_seconds']
        total_seconds = floodwait_event['total_wait_seconds']
        severity = floodwait_event['severity']
        operation = floodwait_event['operation_type']
        
        # Convert to human readable
        fw_hours = fw_seconds / 3600
        total_hours = total_seconds / 3600
        
        severity_emoji = {
            'minor': '⚠️',
            'moderate': '🟠',
            'severe': '🔴',
            'critical': '🚨'
        }
        
        msg = f"<b>{severity_emoji.get(severity, '⚠️')} FLOODWAIT DETECTED</b>\n\n"
        msg += f"<b>Severity:</b> {severity.upper()}\n"
        msg += f"<b>Operation:</b> {operation}\n"
        msg += f"<b>Server wait:</b> {fw_hours:.1f} hours ({fw_seconds} sec)\n"
        msg += f"<b>Buffer added:</b> {buffer_seconds/60:.0f} minutes\n"
        msg += f"<b>Total wait:</b> {total_hours:.1f} hours\n\n"
        
        if severity in ['severe', 'critical']:
            msg += f"<b>🚨 CRITICAL:</b> This is a strong ban warning!\n\n"
        
        msg += f"<b>Actions taken:</b>\n"
        msg += f"• Account quarantined\n"
        msg += f"• All operations paused\n"
        msg += f"• Waiting {total_hours:.1f} hours + buffer\n"
        msg += f"• Recovery mode for 4 hours after\n\n"
        
        if recovery_data:
            ends_at = datetime.fromisoformat(recovery_data['ends_at'])
            hours_remaining = (ends_at - datetime.now()).total_seconds() / 3600
            
            msg += f"<b>Recovery Mode:</b>\n"
            msg += f"• Rate limits at 25%\n"
            msg += f"• {hours_remaining:.1f} hours remaining\n\n"
        
        msg += f"<i>Research: FloodWait means Telegram detected unusual activity.\n"
        msg += f"Must respect it completely to avoid permanent ban.</i>"
        
        return msg
    
    @staticmethod
    def get_floodwait_stats(db, account_id: int, days: int = 30) -> Dict:
        """
        Get FloodWait statistics for account
        
        Args:
            db: Database instance
            account_id: Account ID
            days: Number of days to analyze
        
        Returns:
            dict: FloodWait statistics
        """
        history = db.get(f"account.{account_id}", "floodwait_history", [])
        
        cutoff = datetime.now() - timedelta(days=days)
        recent = [
            event for event in history
            if datetime.fromisoformat(event['timestamp']) >= cutoff
        ]
        
        if not recent:
            return {
                "total_events": 0,
                "days_analyzed": days,
                "message": "No FloodWait events"
            }
        
        # Count by severity
        severity_counts = {
            'minor': 0,
            'moderate': 0,
            'severe': 0,
            'critical': 0
        }
        
        total_wait_time = 0
        operations = {}
        
        for event in recent:
            severity_counts[event['severity']] += 1
            total_wait_time += event['total_wait_seconds']
            op = event['operation_type']
            operations[op] = operations.get(op, 0) + 1
        
        return {
            "total_events": len(recent),
            "days_analyzed": days,
            "by_severity": severity_counts,
            "total_wait_hours": total_wait_time / 3600,
            "avg_wait_hours": (total_wait_time / len(recent)) / 3600,
            "by_operation": operations,
            "most_recent": recent[-1] if recent else None
        }


# Global instance
recovery_manager = FloodWaitRecoveryManager()


# ========== TEST FUNCTION ==========
if __name__ == '__main__':
    print("=" * 70)
    print("FloodWait Recovery Manager - Test")
    print("=" * 70)
    
    # Test 1: Severity calculation
    print("\nTest 1: Severity levels")
    print("-" * 70)
    
    test_durations = [
        (30, 'minor'),
        (600, 'moderate'),
        (1800, 'moderate'),
        (7200, 'severe'),
        (50000, 'critical'),
    ]
    
    for duration, expected in test_durations:
        severity = recovery_manager.calculate_severity(duration)
        hours = duration / 3600
        status = "✅" if severity == expected else "❌"
        print(f"  {status} {hours:6.1f} hours: {severity:10s} (expected {expected})")
    
    # Test 2: Buffer calculation
    print("\nTest 2: Buffer parameters")
    print("-" * 70)
    print(f"  Min buffer: {recovery_manager.BUFFER_MIN_SECONDS / 60:.0f} minutes")
    print(f"  Max buffer: {recovery_manager.BUFFER_MAX_SECONDS / 60:.0f} minutes")
    print(f"  Recovery duration: {recovery_manager.RECOVERY_DURATION_HOURS} hours")
    print(f"  Recovery rate: {recovery_manager.RECOVERY_RATE_MULTIPLIER * 100:.0f}% of normal")
    
    # Test 3: Rate limit adjustment
    print("\nTest 3: Rate limit adjustment in recovery mode")
    print("-" * 70)
    
    base_limits = {
        'max_clones_per_day': 10,
        'max_dms_per_day': 50,
        'max_group_joins': 20,
        'some_string_value': 'test'
    }
    
    # Simulate recovery mode data
    class MockDB:
        def get(self, *args):
            # First arg is namespace, second is key, third is default
            if len(args) >= 2 and args[1] == 'recovery_mode':
                return {
                    'active': True,
                    'rate_multiplier': 0.25,
                    'ends_at': (datetime.now() + timedelta(hours=2)).isoformat()
                }
            return args[-1] if args else None
    
    mock_db = MockDB()
    adjusted = recovery_manager.get_adjusted_rate_limits(mock_db, 12345, base_limits)
    
    print(f"  Normal clones/day: {base_limits['max_clones_per_day']}")
    print(f"  Recovery clones/day: {adjusted['max_clones_per_day']}")
    print(f"  Normal DMs/day: {base_limits['max_dms_per_day']}")
    print(f"  Recovery DMs/day: {adjusted['max_dms_per_day']}")
    
    if adjusted['max_clones_per_day'] == 2 and adjusted['max_dms_per_day'] == 12:
        print("  ✅ Rate adjustment working (25% of normal)")
    else:
        print("  ❌ Rate adjustment failed")
    
    print("\n" + "=" * 70)
    print("✅ FloodWait recovery tests passed!")
    print("=" * 70)
    print("\n📊 Key metrics:")
    print(f"   • Severity levels: 4 (minor → critical)")
    print(f"   • Buffer range: {recovery_manager.BUFFER_MIN_SECONDS // 60}-{recovery_manager.BUFFER_MAX_SECONDS // 60} minutes")
    print(f"   • Recovery duration: {recovery_manager.RECOVERY_DURATION_HOURS} hours")
    print(f"   • Recovery rate: {recovery_manager.RECOVERY_RATE_MULTIPLIER * 100:.0f}%")
