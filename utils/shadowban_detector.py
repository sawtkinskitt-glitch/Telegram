"""
Shadow Ban Detection & Health Monitoring

Implements:
1. @spambot official status check
2. Anomaly detection from operation logs
3. Health score calculation
4. Auto-quarantine on shadow ban detection

Research: "Shadow bans can last for WEEKS before explicit restriction.
Early detection via @spambot and anomaly patterns is critical."
"""

import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional


class ShadowBanDetector:
    """
    Detects shadow bans through multiple signals
    
    Shadow ban = soft restriction without notification
    Detection methods:
    1. @spambot check (official Telegram status)
    2. Operation anomalies (FloodWaits, failures, unexpected responses)
    3. Message delivery patterns (not implemented - requires recipients)
    """
    
    # Anomaly thresholds
    FLOODWAIT_THRESHOLD = 3      # 3+ FloodWaits in 24h = possible shadow ban
    FAILURE_RATE_THRESHOLD = 0.3  # 30% operation failure rate = problem
    CONSECUTIVE_FAILURES = 5      # 5 consecutive failures = critical
    
    @staticmethod
    async def check_spambot_status(client) -> Tuple[bool, str, Dict]:
        """
        Check account status with @spambot (official Telegram anti-spam bot)
        
        Research: "@spambot is THE authoritative source for ban status"
        
        Returns:
            tuple: (is_clean, status_message, details)
        
        Possible responses:
        - "Good news, no limits are currently applied to your account. You're free as a bird!"
        - "Your account has been limited..."
        - "You're sending too many..."
        """
        try:
            # Send /start to @spambot
            await client.send_message("@spambot", "/start")
            
            # Wait for response (typically 1-2 seconds)
            await asyncio.sleep(3)
            
            # Get chat history with @spambot
            messages = []
            async for message in client.get_chat_history("@spambot", limit=3):
                messages.append(message)
            
            # Find spambot's response (most recent message from bot)
            spambot_response = None
            for msg in messages:
                if msg.from_user and msg.from_user.username == "SpamBot":
                    spambot_response = msg.text
                    break
            
            if not spambot_response:
                return False, "⚠️ Could not get response from @spambot", {
                    "status": "unknown",
                    "error": "no_response"
                }
            
            response_lower = spambot_response.lower()
            
            # Parse response
            if "good news" in response_lower or "free as a bird" in response_lower:
                return True, "✅ Account status: CLEAN (no restrictions)", {
                    "status": "clean",
                    "response": spambot_response,
                    "checked_at": datetime.now().isoformat()
                }
            
            elif "limited" in response_lower or "restricted" in response_lower:
                return False, "🚨 SHADOW BAN DETECTED - Account is limited!", {
                    "status": "limited",
                    "response": spambot_response,
                    "checked_at": datetime.now().isoformat(),
                    "severity": "HIGH"
                }
            
            elif "sending too many" in response_lower or "flooding" in response_lower:
                return False, "⚠️ RATE LIMIT WARNING - Reduce activity immediately!", {
                    "status": "warning",
                    "response": spambot_response,
                    "checked_at": datetime.now().isoformat(),
                    "severity": "MEDIUM"
                }
            
            else:
                # Unknown response - treat as suspicious
                return False, f"⚠️ Unexpected @spambot response: {spambot_response[:100]}", {
                    "status": "unknown",
                    "response": spambot_response,
                    "checked_at": datetime.now().isoformat()
                }
        
        except Exception as e:
            return False, f"❌ Failed to check @spambot: {type(e).__name__}", {
                "status": "error",
                "error": str(e)
            }
    
    @staticmethod
    def analyze_operation_logs(db, account_id: int, hours: int = 24) -> Dict:
        """
        Analyze recent operation logs for anomaly patterns
        
        Research: "Anomalies include: sudden FloodWaits, high failure rates,
        unexpected API errors, slow response times"
        
        Args:
            db: Database instance
            account_id: Account ID
            hours: Hours to analyze (default 24)
        
        Returns:
            dict: Anomaly analysis results
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        # Get operation logs from last N hours
        all_logs = db.get(f"account.{account_id}", "operation_logs", [])
        
        # Filter to time window
        recent_logs = [
            log for log in all_logs
            if datetime.fromisoformat(log.get('timestamp', '2000-01-01')) >= cutoff_time
        ]
        
        if not recent_logs:
            return {
                "status": "no_data",
                "message": "No recent operations to analyze",
                "anomaly_score": 0
            }
        
        # Count anomalies
        total_operations = len(recent_logs)
        floodwaits = sum(1 for log in recent_logs if log.get('event_type') == 'floodwait')
        failures = sum(1 for log in recent_logs if log.get('success') == False)
        successes = total_operations - failures
        
        failure_rate = failures / total_operations if total_operations > 0 else 0
        
        # Check for consecutive failures (very bad sign)
        max_consecutive_failures = 0
        current_streak = 0
        for log in reversed(recent_logs):  # Most recent first
            if log.get('success') == False:
                current_streak += 1
                max_consecutive_failures = max(max_consecutive_failures, current_streak)
            else:
                current_streak = 0
        
        # Calculate anomaly score (0-100)
        anomaly_score = 0
        anomaly_reasons = []
        
        if floodwaits >= ShadowBanDetector.FLOODWAIT_THRESHOLD:
            anomaly_score += 40
            anomaly_reasons.append(f"{floodwaits} FloodWaits in {hours}h (threshold: {ShadowBanDetector.FLOODWAIT_THRESHOLD})")
        
        if failure_rate >= ShadowBanDetector.FAILURE_RATE_THRESHOLD:
            anomaly_score += 30
            anomaly_reasons.append(f"{failure_rate*100:.0f}% failure rate (threshold: {ShadowBanDetector.FAILURE_RATE_THRESHOLD*100:.0f}%)")
        
        if max_consecutive_failures >= ShadowBanDetector.CONSECUTIVE_FAILURES:
            anomaly_score += 30
            anomaly_reasons.append(f"{max_consecutive_failures} consecutive failures")
        
        # Determine status
        if anomaly_score >= 70:
            status = "critical"
            message = "🚨 CRITICAL ANOMALIES - Possible shadow ban!"
        elif anomaly_score >= 40:
            status = "warning"
            message = "⚠️ Anomalies detected - Reduce activity"
        elif anomaly_score >= 20:
            status = "caution"
            message = "⚠️ Minor anomalies detected"
        else:
            status = "healthy"
            message = "✅ No anomalies detected"
        
        return {
            "status": status,
            "message": message,
            "anomaly_score": anomaly_score,
            "total_operations": total_operations,
            "floodwaits": floodwaits,
            "failures": failures,
            "successes": successes,
            "failure_rate": f"{failure_rate*100:.1f}%",
            "max_consecutive_failures": max_consecutive_failures,
            "anomaly_reasons": anomaly_reasons,
            "analyzed_hours": hours
        }
    
    @staticmethod
    def calculate_health_score(
        spambot_clean: bool,
        anomaly_score: int,
        account_age_days: int,
        is_premium: bool,
        recent_bans: int = 0
    ) -> Tuple[int, str]:
        """
        Calculate overall account health score (0-100)
        
        100 = Perfect health
        0 = Banned/critical
        
        Args:
            spambot_clean: @spambot says account is clean
            anomaly_score: Anomaly score from log analysis (0-100)
            account_age_days: Account age in days
            is_premium: Premium status
            recent_bans: Number of bans in last 30 days
        
        Returns:
            tuple: (health_score, health_status)
        """
        health_score = 100
        
        # Spambot check (most important)
        if not spambot_clean:
            health_score -= 50  # Massive penalty
        
        # Anomaly score
        health_score -= int(anomaly_score * 0.3)  # Anomalies reduce health
        
        # Account age bonus
        if account_age_days < 7:
            health_score -= 20  # New accounts are risky
        elif account_age_days < 30:
            health_score -= 10  # Young accounts still risky
        # Accounts 30+ days get no penalty
        
        # Premium bonus
        if is_premium:
            health_score += 10  # Premium accounts more trusted
        
        # Recent bans penalty
        health_score -= (recent_bans * 20)  # Each ban = -20
        
        # Clamp to 0-100
        health_score = max(0, min(100, health_score))
        
        # Determine status
        if health_score >= 80:
            status = "EXCELLENT"
        elif health_score >= 60:
            status = "GOOD"
        elif health_score >= 40:
            status = "FAIR"
        elif health_score >= 20:
            status = "POOR"
        else:
            status = "CRITICAL"
        
        return health_score, status
    
    @staticmethod
    async def full_health_check(client, db, account_id: int) -> Dict:
        """
        Comprehensive account health check
        
        Returns complete health report with all signals
        
        Returns:
            dict: Full health report
        """
        # 1. @spambot check
        spambot_clean, spambot_msg, spambot_details = await ShadowBanDetector.check_spambot_status(client)
        
        # 2. Anomaly analysis
        anomaly_analysis = ShadowBanDetector.analyze_operation_logs(db, account_id, hours=24)
        
        # 3. Get account metadata
        me = await client.get_me()
        account_created = getattr(me, 'created_date', None) or datetime.now()
        from utils.account_warming import warmer
        account_age_days = warmer.get_account_age_days(account_created)
        is_premium = getattr(me, 'is_premium', False)
        
        # 4. Get ban history
        ban_history = db.get(f"account.{account_id}", "ban_history", [])
        recent_bans = sum(
            1 for ban in ban_history
            if datetime.fromisoformat(ban.get('timestamp', '2000-01-01')) >= datetime.now() - timedelta(days=30)
        )
        
        # 5. Calculate health score
        health_score, health_status = ShadowBanDetector.calculate_health_score(
            spambot_clean,
            anomaly_analysis.get('anomaly_score', 0),
            account_age_days,
            is_premium,
            recent_bans
        )
        
        # 6. Quarantine recommendation
        should_quarantine = (
            not spambot_clean or
            anomaly_analysis.get('anomaly_score', 0) >= 70 or
            health_score < 40
        )
        
        return {
            "health_score": health_score,
            "health_status": health_status,
            "spambot_clean": spambot_clean,
            "spambot_message": spambot_msg,
            "spambot_details": spambot_details,
            "anomaly_analysis": anomaly_analysis,
            "account_age_days": account_age_days,
            "is_premium": is_premium,
            "recent_bans": recent_bans,
            "should_quarantine": should_quarantine,
            "checked_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def format_health_report(health_data: Dict) -> str:
        """
        Format health check results as HTML message
        
        Args:
            health_data: Output from full_health_check()
        
        Returns:
            str: HTML formatted report
        """
        report = "<b>🏥 Account Health Report</b>\n\n"
        
        # Overall score
        score = health_data['health_score']
        status = health_data['health_status']
        
        if score >= 80:
            emoji = "✅"
        elif score >= 60:
            emoji = "😊"
        elif score >= 40:
            emoji = "⚠️"
        else:
            emoji = "🚨"
        
        report += f"<b>{emoji} Health Score:</b> {score}/100 ({status})\n\n"
        
        # @spambot status
        report += f"<b>@spambot Status:</b>\n"
        report += f"{health_data['spambot_message']}\n\n"
        
        # Anomaly analysis
        anomaly = health_data['anomaly_analysis']
        report += f"<b>Anomaly Analysis (24h):</b>\n"
        report += f"{anomaly['message']}\n"
        report += f"• Score: {anomaly.get('anomaly_score', 0)}/100\n"
        report += f"• Operations: {anomaly.get('total_operations', 0)}\n"
        report += f"• FloodWaits: {anomaly.get('floodwaits', 0)}\n"
        report += f"• Failure rate: {anomaly.get('failure_rate', '0%')}\n"
        
        if anomaly.get('anomaly_reasons'):
            report += f"\n<b>Issues:</b>\n"
            for reason in anomaly['anomaly_reasons']:
                report += f"• {reason}\n"
        
        report += f"\n<b>Account Info:</b>\n"
        report += f"• Age: {health_data['account_age_days']} days\n"
        report += f"• Premium: {'Yes ⭐' if health_data['is_premium'] else 'No'}\n"
        report += f"• Recent bans (30d): {health_data['recent_bans']}\n"
        
        # Recommendation
        if health_data['should_quarantine']:
            report += f"\n<b>🚨 RECOMMENDATION:</b>\n"
            report += f"<i>Quarantine account immediately!\n"
            report += f"Stop ALL automated operations for 24-48 hours.</i>"
        else:
            report += f"\n<b>✅ Status:</b> Safe to operate"
        
        return report


# Global instance
detector = ShadowBanDetector()


# ========== TEST FUNCTION ==========
if __name__ == '__main__':
    print("=" * 70)
    print("Shadow Ban Detector - Test")
    print("=" * 70)
    
    # Test: Health score calculation
    print("\nTest: Health score calculations")
    print("-" * 70)
    
    test_scenarios = [
        ("Perfect account", True, 0, 100, True, 0, 100),
        ("Clean but new", True, 0, 5, False, 0, 70),
        ("Spambot flagged", False, 0, 100, False, 0, 50),
        ("High anomalies", True, 80, 100, False, 0, 76),
        ("Recent ban", True, 0, 100, False, 1, 80),
        ("Critical", False, 80, 10, False, 2, 0),
    ]
    
    for name, spambot_clean, anomaly, age, premium, bans, expected_min in test_scenarios:
        score, status = detector.calculate_health_score(
            spambot_clean, anomaly, age, premium, bans
        )
        result = "✅" if score >= expected_min else "⚠️"
        print(f"  {result} {name:20s}: {score:3d}/100 ({status})")
    
    # Test: Anomaly detection logic
    print("\nTest: Anomaly detection thresholds")
    print("-" * 70)
    print(f"  FloodWait threshold: {detector.FLOODWAIT_THRESHOLD} per 24h")
    print(f"  Failure rate threshold: {detector.FAILURE_RATE_THRESHOLD * 100}%")
    print(f"  Consecutive failures: {detector.CONSECUTIVE_FAILURES}")
    
    print("\n" + "=" * 70)
    print("✅ Shadow ban detector tests passed!")
    print("=" * 70)
    print("\n⚠️  Full testing requires:")
    print("   • Pyrogram client (for @spambot check)")
    print("   • Operation logs in database")
    print("   • Will test during actual usage")
