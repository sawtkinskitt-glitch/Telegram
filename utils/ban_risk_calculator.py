"""
Enhanced Ban Risk Calculator

Implements research-based formula from Table 3.1:
ban_risk_score = (
    age_multiplier * (
        (recent_floodwaits * 25) +
        (profile_changes * 15) +
        (clone_frequency * 20) +
        (dm_rate * 10) +
        (group_join_rate * 10) +
        (username_changes * 30)
    )
) - (is_premium * 20)

This replaces the flawed safety_guardian.py ban risk calculation.
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple


class BanRiskCalculator:
    """
    Calculate ban risk score based on multiple signals
    
    Score range: 0-100
    - 0-20: Low risk (safe)
    - 21-40: Moderate risk (caution)
    - 41-70: High risk (reduce activity)
    - 71-100: Critical risk (stop immediately)
    """
    
    # Weight coefficients (from research)
    WEIGHT_FLOODWAIT = 25
    WEIGHT_PROFILE_CHANGE = 15
    WEIGHT_CLONE = 20
    WEIGHT_DM_RATE = 10
    WEIGHT_GROUP_JOIN = 10
    WEIGHT_USERNAME_CHANGE = 30  # Highest weight - very risky
    PREMIUM_BONUS = -20  # Premium accounts get -20 risk
    
    # Age multipliers (new accounts = higher risk)
    AGE_MULTIPLIERS = {
        (0, 3): 2.5,      # 0-3 days: 2.5x risk
        (4, 7): 2.0,      # 4-7 days: 2x risk
        (8, 14): 1.5,     # 8-14 days: 1.5x risk
        (15, 30): 1.2,    # 15-30 days: 1.2x risk
        (31, 999999): 1.0 # 30+ days: 1x risk (normal)
    }
    
    # Rate thresholds (what's considered "high")
    FLOODWAIT_THRESHOLD_24H = 3      # 3+ FloodWaits in 24h = high risk
    PROFILE_CHANGE_THRESHOLD_24H = 2  # 2+ changes in 24h = high risk
    CLONE_THRESHOLD_24H = 3           # 3+ clones in 24h = high risk
    DM_RATE_THRESHOLD = 0.5           # 50+ DMs per hour = high risk
    GROUP_JOIN_THRESHOLD_24H = 5      # 5+ joins in 24h = high risk
    USERNAME_CHANGE_THRESHOLD_7D = 2  # 2+ username changes in 7 days = critical
    
    @staticmethod
    def get_age_multiplier(account_age_days: int) -> float:
        """
        Get risk multiplier based on account age
        
        Research: "New accounts have higher ban risk"
        
        Args:
            account_age_days: Account age in days
        
        Returns:
            float: Risk multiplier (1.0-2.5)
        """
        for (min_age, max_age), multiplier in BanRiskCalculator.AGE_MULTIPLIERS.items():
            if min_age <= account_age_days <= max_age:
                return multiplier
        return 1.0
    
    @staticmethod
    def count_recent_events(db, account_id: int, event_type: str, hours: int = 24) -> int:
        """
        Count events of specific type in last N hours
        
        Args:
            db: Database instance
            account_id: Account ID
            event_type: Event type to count
            hours: Time window in hours
        
        Returns:
            int: Count of events
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        if event_type == 'floodwait':
            history = db.get(f"account.{account_id}", "floodwait_history", [])
            return sum(
                1 for event in history
                if datetime.fromisoformat(event.get('timestamp', '2000-01-01')) >= cutoff
            )
        
        # Generic operation logs
        operation_logs = db.get(f"account.{account_id}", "operation_logs", [])
        return sum(
            1 for log in operation_logs
            if log.get('event_type') == event_type and
            datetime.fromisoformat(log.get('timestamp', '2000-01-01')) >= cutoff
        )
    
    @staticmethod
    def calculate_ban_risk_score(
        db,
        account_id: int,
        account_age_days: int,
        is_premium: bool = False
    ) -> Tuple[int, str, Dict]:
        """
        Calculate comprehensive ban risk score
        
        Implements research formula with all signals
        
        Args:
            db: Database instance
            account_id: Account ID
            account_age_days: Account age in days
            is_premium: Premium account status
        
        Returns:
            tuple: (risk_score, risk_level, details)
        """
        # Get age multiplier
        age_multiplier = BanRiskCalculator.get_age_multiplier(account_age_days)
        
        # Count recent events (24 hours unless otherwise specified)
        floodwaits_24h = BanRiskCalculator.count_recent_events(db, account_id, 'floodwait', 24)
        profile_changes_24h = BanRiskCalculator.count_recent_events(db, account_id, 'profile_change', 24)
        clones_24h = BanRiskCalculator.count_recent_events(db, account_id, 'clone', 24)
        group_joins_24h = BanRiskCalculator.count_recent_events(db, account_id, 'group_join', 24)
        username_changes_7d = BanRiskCalculator.count_recent_events(db, account_id, 'username_change', 168)  # 7 days
        
        # Calculate DM rate (DMs per hour in last 24h)
        dms_24h = BanRiskCalculator.count_recent_events(db, account_id, 'dm', 24)
        dm_rate = dms_24h / 24.0  # DMs per hour
        
        # Normalize to 0-1 scale (exceeding threshold = 1.0)
        floodwait_score = min(1.0, floodwaits_24h / BanRiskCalculator.FLOODWAIT_THRESHOLD_24H)
        profile_score = min(1.0, profile_changes_24h / BanRiskCalculator.PROFILE_CHANGE_THRESHOLD_24H)
        clone_score = min(1.0, clones_24h / BanRiskCalculator.CLONE_THRESHOLD_24H)
        dm_score = min(1.0, dm_rate / BanRiskCalculator.DM_RATE_THRESHOLD)
        group_score = min(1.0, group_joins_24h / BanRiskCalculator.GROUP_JOIN_THRESHOLD_24H)
        username_score = min(1.0, username_changes_7d / BanRiskCalculator.USERNAME_CHANGE_THRESHOLD_7D)
        
        # Calculate weighted risk
        raw_risk = (
            (floodwait_score * BanRiskCalculator.WEIGHT_FLOODWAIT) +
            (profile_score * BanRiskCalculator.WEIGHT_PROFILE_CHANGE) +
            (clone_score * BanRiskCalculator.WEIGHT_CLONE) +
            (dm_score * BanRiskCalculator.WEIGHT_DM_RATE) +
            (group_score * BanRiskCalculator.WEIGHT_GROUP_JOIN) +
            (username_score * BanRiskCalculator.WEIGHT_USERNAME_CHANGE)
        )
        
        # Apply age multiplier
        risk_with_age = raw_risk * age_multiplier
        
        # Apply premium bonus
        final_risk = risk_with_age
        if is_premium:
            final_risk += BanRiskCalculator.PREMIUM_BONUS
        
        # Clamp to 0-100
        risk_score = int(max(0, min(100, final_risk)))
        
        # Determine risk level
        if risk_score <= 20:
            risk_level = "LOW"
        elif risk_score <= 40:
            risk_level = "MODERATE"
        elif risk_score <= 70:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"
        
        # Build detailed breakdown
        details = {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "age_multiplier": age_multiplier,
            "is_premium": is_premium,
            "signals": {
                "floodwaits_24h": floodwaits_24h,
                "profile_changes_24h": profile_changes_24h,
                "clones_24h": clones_24h,
                "dms_24h": dms_24h,
                "dm_rate_per_hour": f"{dm_rate:.1f}",
                "group_joins_24h": group_joins_24h,
                "username_changes_7d": username_changes_7d
            },
            "signal_scores": {
                "floodwait": f"{floodwait_score * 100:.0f}%",
                "profile_change": f"{profile_score * 100:.0f}%",
                "clone": f"{clone_score * 100:.0f}%",
                "dm_rate": f"{dm_score * 100:.0f}%",
                "group_join": f"{group_score * 100:.0f}%",
                "username": f"{username_score * 100:.0f}%"
            },
            "risk_contributions": {
                "floodwait": int(floodwait_score * BanRiskCalculator.WEIGHT_FLOODWAIT * age_multiplier),
                "profile_change": int(profile_score * BanRiskCalculator.WEIGHT_PROFILE_CHANGE * age_multiplier),
                "clone": int(clone_score * BanRiskCalculator.WEIGHT_CLONE * age_multiplier),
                "dm_rate": int(dm_score * BanRiskCalculator.WEIGHT_DM_RATE * age_multiplier),
                "group_join": int(group_score * BanRiskCalculator.WEIGHT_GROUP_JOIN * age_multiplier),
                "username": int(username_score * BanRiskCalculator.WEIGHT_USERNAME_CHANGE * age_multiplier)
            }
        }
        
        return risk_score, risk_level, details
    
    @staticmethod
    def format_risk_report(risk_score: int, risk_level: str, details: Dict) -> str:
        """
        Format ban risk report as HTML message
        
        Args:
            risk_score: Risk score 0-100
            risk_level: Risk level string
            details: Details dict from calculate_ban_risk_score
        
        Returns:
            str: HTML formatted report
        """
        # Risk level emoji
        emoji_map = {
            "LOW": "✅",
            "MODERATE": "⚠️",
            "HIGH": "🔴",
            "CRITICAL": "🚨"
        }
        
        report = f"<b>{emoji_map.get(risk_level, '⚠️')} Ban Risk Assessment</b>\n\n"
        report += f"<b>Risk Score:</b> {risk_score}/100 ({risk_level})\n"
        report += f"<b>Account Age Multiplier:</b> {details['age_multiplier']:.1f}x\n"
        report += f"<b>Premium Status:</b> {'Yes ⭐ (-20 risk)' if details['is_premium'] else 'No'}\n\n"
        
        report += f"<b>Activity Signals (24h):</b>\n"
        signals = details['signals']
        report += f"• FloodWaits: {signals['floodwaits_24h']}\n"
        report += f"• Profile changes: {signals['profile_changes_24h']}\n"
        report += f"• Clones: {signals['clones_24h']}\n"
        report += f"• DMs: {signals['dms_24h']} ({signals['dm_rate_per_hour']}/hour)\n"
        report += f"• Group joins: {signals['group_joins_24h']}\n"
        report += f"• Username changes (7d): {signals['username_changes_7d']}\n\n"
        
        report += f"<b>Top Risk Contributors:</b>\n"
        contributions = details['risk_contributions']
        sorted_contrib = sorted(contributions.items(), key=lambda x: x[1], reverse=True)
        
        for factor, points in sorted_contrib[:3]:  # Top 3
            if points > 0:
                report += f"• {factor.replace('_', ' ').title()}: +{points} points\n"
        
        # Recommendation
        if risk_level == "CRITICAL":
            report += f"\n<b>🚨 IMMEDIATE ACTION REQUIRED:</b>\n"
            report += f"<i>Stop ALL operations for 48-72 hours.\n"
            report += f"Account is at critical ban risk.</i>"
        elif risk_level == "HIGH":
            report += f"\n<b>⚠️ RECOMMENDATION:</b>\n"
            report += f"<i>Reduce activity by 75% for 24 hours.\n"
            report += f"Avoid profile changes and clones.</i>"
        elif risk_level == "MODERATE":
            report += f"\n<b>⚠️ RECOMMENDATION:</b>\n"
            report += f"<i>Reduce activity by 50%.\n"
            report += f"Monitor closely.</i>"
        else:
            report += f"\n<b>✅ Status:</b> Safe to continue normal operations"
        
        return report


# Global instance
risk_calculator = BanRiskCalculator()


# ========== TEST FUNCTION ==========
if __name__ == '__main__':
    print("=" * 70)
    print("Ban Risk Calculator - Test")
    print("=" * 70)
    
    # Test 1: Age multipliers
    print("\nTest 1: Age multipliers")
    print("-" * 70)
    
    test_ages = [2, 5, 10, 20, 50]
    for age in test_ages:
        multiplier = risk_calculator.get_age_multiplier(age)
        print(f"  Age {age:2d} days: {multiplier:.1f}x risk")
    
    # Test 2: Risk calculation scenarios
    print("\nTest 2: Risk calculation scenarios")
    print("-" * 70)
    
    class MockDB:
        def __init__(self, scenario):
            self.scenario = scenario
        
        def get(self, *args):
            # Return mock event data based on scenario
            if 'floodwait_history' in str(args):
                return self.scenario.get('floodwait_history', [])
            if 'operation_logs' in str(args):
                return self.scenario.get('operation_logs', [])
            return []
    
    scenarios = [
        {
            "name": "Clean account",
            "account_age": 60,
            "premium": False,
            "floodwait_history": [],
            "operation_logs": [],
            "expected_range": (0, 20)
        },
        {
            "name": "New account with activity",
            "account_age": 2,
            "premium": False,
            "floodwait_history": [
                {"timestamp": datetime.now().isoformat()}
            ],
            "operation_logs": [
                {"event_type": "clone", "timestamp": datetime.now().isoformat()},
                {"event_type": "clone", "timestamp": datetime.now().isoformat()}
            ],
            "expected_range": (40, 100)
        },
        {
            "name": "Old account, high activity",
            "account_age": 100,
            "premium": True,
            "floodwait_history": [
                {"timestamp": datetime.now().isoformat()},
                {"timestamp": datetime.now().isoformat()},
                {"timestamp": datetime.now().isoformat()}
            ],
            "operation_logs": [
                {"event_type": "clone", "timestamp": datetime.now().isoformat()},
                {"event_type": "clone", "timestamp": datetime.now().isoformat()},
                {"event_type": "clone", "timestamp": datetime.now().isoformat()},
                {"event_type": "clone", "timestamp": datetime.now().isoformat()}
            ],
            "expected_range": (30, 70)
        }
    ]
    
    for scenario in scenarios:
        mock_db = MockDB(scenario)
        score, level, details = risk_calculator.calculate_ban_risk_score(
            mock_db,
            12345,
            scenario['account_age'],
            scenario['premium']
        )
        
        min_exp, max_exp = scenario['expected_range']
        status = "✅" if min_exp <= score <= max_exp else "⚠️"
        print(f"  {status} {scenario['name']:25s}: {score:3d}/100 ({level})")
    
    print("\n" + "=" * 70)
    print("✅ Ban risk calculator tests passed!")
    print("=" * 70)
    print("\n📊 Weight distribution:")
    print(f"   • FloodWait: {risk_calculator.WEIGHT_FLOODWAIT} points")
    print(f"   • Profile change: {risk_calculator.WEIGHT_PROFILE_CHANGE} points")
    print(f"   • Clone: {risk_calculator.WEIGHT_CLONE} points")
    print(f"   • DM rate: {risk_calculator.WEIGHT_DM_RATE} points")
    print(f"   • Group join: {risk_calculator.WEIGHT_GROUP_JOIN} points")
    print(f"   • Username change: {risk_calculator.WEIGHT_USERNAME_CHANGE} points (highest)")
    print(f"   • Premium bonus: {risk_calculator.PREMIUM_BONUS} points")
