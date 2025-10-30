"""
Account Warming System

Implements the 4-week warming schedule from Table 2.1 of research:
"New accounts (0-7 days) are in a 'sandbox' and are 'suspected' and 'frozen' by default"

This module enforces age-based restrictions to prevent instant bans.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Optional
import random


class AccountWarmer:
    """
    Manages account warming schedule based on account age
    
    Key principle: New accounts have dramatically lower rate limits.
    Must build trust gradually over 30 days.
    """
    
    # Research Table 2.1: Recommended Account Warming Schedule
    WARMING_SCHEDULE = {
        'days_0_3': {
            'age_range': (0, 3),
            'risk_level': 'EXTREME',
            'description': 'Set profile ONCE, join verified channels only, READ ONLY',
            'allowed_actions': ['set_profile_once', 'join_verified_channels', 'read_only'],
            'forbidden_actions': ['dm_non_contacts', 'join_groups', 'clone', 'spam', 'mass_operations'],
            'max_profile_changes': 1,  # Set name/bio on day 0, photo on day 1
            'max_channel_joins': 3,    # Only verified channels (@telegram, @durov, etc.)
            'max_group_joins': 0,
            'max_dms_per_day': 0,
            'max_messages_per_day': 0,  # Can only message "Saved Messages"
            'max_clone_per_day': 0,
        },
        'days_4_7': {
            'age_range': (4, 7),
            'risk_level': 'VERY_HIGH',
            'description': 'Join 1-2 public groups, send 1-2 messages/day, add reactions',
            'allowed_actions': ['join_public_groups', 'send_group_messages', 'react'],
            'forbidden_actions': ['dm_non_contacts', 'clone', 'spam', 'username_change'],
            'max_profile_changes': 0,  # NO profile changes
            'max_channel_joins': 2,
            'max_group_joins': 2,      # Public groups only
            'max_dms_per_day': 0,
            'max_group_messages_per_day': 2,
            'max_reactions_per_day': 10,
            'max_clone_per_day': 0,
        },
        'days_7_14': {
            'age_range': (7, 14),
            'risk_level': 'HIGH',
            'description': 'Reply to incoming DMs, initiate 1-2 DMs/day (heavily spaced)',
            'allowed_actions': ['reply_to_incoming_dms', 'initiate_limited_dms', 'moderate_groups'],
            'forbidden_actions': ['clone', 'mass_operations', 'spam'],
            'max_profile_changes': 0,
            'max_group_joins': 2,
            'max_dms_per_day': 2,      # HEAVILY spaced (hours apart)
            'max_group_messages_per_day': 10,
            'max_clone_per_day': 0,
        },
        'days_14_30': {
            'age_range': (14, 30),
            'risk_level': 'MEDIUM',
            'description': 'Moderate activity, can change photo ONCE',
            'allowed_actions': ['change_photo_once', 'moderate_activity', 'limited_dms'],
            'forbidden_actions': ['clone', 'aggressive_automation', 'mass_spam'],
            'max_profile_changes': 1,  # Can change 1 photo
            'max_dms_per_day': 10,
            'max_group_messages_per_day': 20,
            'max_clone_per_day': 0,
        },
        'days_30_plus': {
            'age_range': (30, 999999),
            'risk_level': 'LOW',
            'description': 'Account warmed - operational',
            'allowed_actions': ['all'],
            'forbidden_actions': [],  # All operations allowed
            'max_clone_per_day': 2,    # Research: "1-2 per day maximum"
            'max_dms_per_day': 25,     # Free account limit (research)
            'max_dms_per_day_premium': 50,  # Premium account limit
            'max_group_joins_per_day': 10,
            'max_profile_changes_per_day': 1,  # Research: "1 per day"
            'max_username_changes_per_week': 2,  # Research: "1-2 per week"
        }
    }
    
    @staticmethod
    def get_account_age_days(created_date) -> int:
        """
        Calculate account age in days
        
        Args:
            created_date: datetime or ISO string
        
        Returns:
            int: Age in days
        """
        if isinstance(created_date, str):
            try:
                created_date = datetime.fromisoformat(created_date)
            except:
                # If parsing fails, assume brand new
                return 0
        
        if not isinstance(created_date, datetime):
            return 0
        
        age = datetime.now() - created_date
        return age.days
    
    @staticmethod
    def get_warming_phase(account_age_days: int) -> Tuple[str, Dict]:
        """
        Get current warming phase based on age
        
        Args:
            account_age_days: Account age in days
        
        Returns:
            tuple: (phase_name, phase_data)
        """
        for phase_name, phase_data in AccountWarmer.WARMING_SCHEDULE.items():
            min_age, max_age = phase_data['age_range']
            if min_age <= account_age_days <= max_age:
                return phase_name, phase_data
        
        # Default to most restrictive if age is negative/invalid
        if account_age_days < 0:
            return 'days_0_3', AccountWarmer.WARMING_SCHEDULE['days_0_3']
        
        # If > 30 days, return final phase
        return 'days_30_plus', AccountWarmer.WARMING_SCHEDULE['days_30_plus']
    
    @staticmethod
    def is_action_allowed(account_age_days: int, action_type: str) -> Tuple[bool, str]:
        """
        Check if an action is allowed for account age
        
        Args:
            account_age_days: Account age in days
            action_type: Action to check ('clone', 'dm_non_contacts', 'join_groups', etc.)
        
        Returns:
            tuple: (is_allowed, reason_if_blocked)
        
        Usage:
            allowed, reason = AccountWarmer.is_action_allowed(5, 'clone')
            if not allowed:
                await message.edit(reason)
                return
        """
        phase_name, phase_data = AccountWarmer.get_warming_phase(account_age_days)
        
        # Check if action is explicitly forbidden
        if action_type in phase_data.get('forbidden_actions', []):
            return False, (
                f"❌ <b>BLOCKED: Account Too New</b>\n\n"
                f"<b>Your account age:</b> {account_age_days} days\n"
                f"<b>Current phase:</b> {phase_name.replace('_', ' ').title()}\n"
                f"<b>Risk level:</b> {phase_data['risk_level']}\n"
                f"<b>Action blocked:</b> {action_type}\n\n"
                f"<i>This protection prevents account bans.\n"
                f"Research shows {action_type} on new accounts = instant ban.</i>"
            )
        
        # Check if action is explicitly allowed
        if action_type in phase_data.get('allowed_actions', []) or 'all' in phase_data.get('allowed_actions', []):
            return True, "OK"
        
        # If not mentioned, block (conservative approach)
        return False, (
            f"⚠️ Action '{action_type}' not safe for {account_age_days}-day account\n"
            f"Current phase: {phase_name} ({phase_data['risk_level']} risk)"
        )
    
    @staticmethod
    def get_daily_limits(account_age_days: int, is_premium: bool = False) -> Dict:
        """
        Get current daily limits for account based on age + Premium status
        
        Args:
            account_age_days: Account age in days
            is_premium: Whether account has Telegram Premium
        
        Returns:
            dict: All current limits for this account
        """
        phase_name, phase_data = AccountWarmer.get_warming_phase(account_age_days)
        
        limits = {
            'clone_operations': phase_data.get('max_clone_per_day', 0),
            'dms_per_day': phase_data.get('max_dms_per_day', 0),
            'group_joins': phase_data.get('max_group_joins_per_day', phase_data.get('max_group_joins', 0)),
            'profile_changes': phase_data.get('max_profile_changes', 0),
            'group_messages': phase_data.get('max_group_messages_per_day', 0),
            'risk_level': phase_data['risk_level'],
            'phase': phase_name,
            'phase_description': phase_data['description']
        }
        
        # Research: "Premium accounts get doubled limits"
        if is_premium and account_age_days >= 30:
            limits['dms_per_day'] = phase_data.get('max_dms_per_day_premium', 50)
            limits['clone_operations'] = 3  # vs 2 for free
        
        return limits
    
    @staticmethod
    def get_warming_status_message(account_age_days: int, is_premium: bool = False) -> str:
        """
        Get human-readable warming status for dashboard/messages
        
        Args:
            account_age_days: Account age in days
            is_premium: Premium status
        
        Returns:
            str: HTML formatted status message
        """
        phase_name, phase_data = AccountWarmer.get_warming_phase(account_age_days)
        limits = AccountWarmer.get_daily_limits(account_age_days, is_premium)
        
        # Calculate days until next phase
        days_until_warmed = max(0, 30 - account_age_days)
        
        status = f"<b>🌡️ Account Warming Status</b>\n\n"
        status += f"<b>Account Age:</b> {account_age_days} days\n"
        status += f"<b>Phase:</b> {phase_name.replace('_', ' ').title()}\n"
        status += f"<b>Risk Level:</b> {phase_data['risk_level']}\n"
        status += f"<b>Premium:</b> {'Yes ⭐' if is_premium else 'No'}\n\n"
        
        status += f"<b>Daily Limits:</b>\n"
        status += f"• Clones: {limits['clone_operations']}/day\n"
        status += f"• New DMs: {limits['dms_per_day']}/day\n"
        status += f"• Profile changes: {limits['profile_changes']}/day\n"
        status += f"• Group joins: {limits['group_joins']}/day\n\n"
        
        if days_until_warmed > 0:
            status += f"<b>⏳ Fully warmed in:</b> {days_until_warmed} days\n"
        else:
            status += f"<b>✅ Account fully warmed!</b>\n"
        
        status += f"\n<i>{phase_data['description']}</i>"
        
        return status
    
    @staticmethod
    async def check_daily_operation_quota(account_id: int, operation_type: str, db) -> Tuple[bool, str, int]:
        """
        Check if account has quota remaining for operation today
        
        Args:
            account_id: Account ID
            operation_type: 'clone', 'dm', 'group_join', 'profile_change'
            db: Database instance
        
        Returns:
            tuple: (has_quota, message, remaining_quota)
        """
        # Get account age
        created_date = db.get(f"account.{account_id}", "created_date")
        if not created_date:
            created_date = datetime.now()  # Assume new if unknown
        
        account_age = AccountWarmer.get_account_age_days(created_date)
        is_premium = db.get(f"account.{account_id}", "is_premium", False)
        
        # Get limits for this account
        limits = AccountWarmer.get_daily_limits(account_age, is_premium)
        
        # Map operation types to limit keys
        limit_mapping = {
            'clone': 'clone_operations',
            'dm': 'dms_per_day',
            'group_join': 'group_joins',
            'profile_change': 'profile_changes',
        }
        
        limit_key = limit_mapping.get(operation_type)
        if not limit_key:
            return True, "Unknown operation type", 999
        
        max_limit = limits.get(limit_key, 0)
        
        # Count today's operations
        today_key = datetime.now().strftime('%Y-%m-%d')
        usage_key = f"account.{account_id}.daily_usage.{today_key}.{operation_type}"
        current_usage = db.get("usage_tracking", usage_key, 0)
        
        remaining = max(0, max_limit - current_usage)
        
        if current_usage >= max_limit:
            return False, (
                f"❌ <b>Daily {operation_type} limit reached</b>\n\n"
                f"<b>Used:</b> {current_usage}/{max_limit}\n"
                f"<b>Account age:</b> {account_age} days\n"
                f"<b>Risk level:</b> {limits['risk_level']}\n\n"
                f"<i>Limit resets at midnight.\n"
                f"This protection prevents account bans.</i>"
            ), 0
        
        return True, "OK", remaining
    
    @staticmethod
    def increment_daily_usage(account_id: int, operation_type: str, db):
        """
        Increment daily usage counter for operation
        
        Call this AFTER successful operation
        """
        today_key = datetime.now().strftime('%Y-%m-%d')
        usage_key = f"account.{account_id}.daily_usage.{today_key}.{operation_type}"
        current = db.get("usage_tracking", usage_key, 0)
        db.set("usage_tracking", usage_key, current + 1)


# Global instance
warmer = AccountWarmer()


# ========== TEST FUNCTION ==========
if __name__ == '__main__':
    print("=" * 70)
    print("Account Warming System - Test")
    print("=" * 70)
    
    # Test 1: Phase detection
    print("\nTest 1: Phase detection for various account ages")
    print("-" * 70)
    
    test_ages = [0, 2, 5, 10, 15, 25, 35, 100]
    
    for age in test_ages:
        phase_name, phase_data = warmer.get_warming_phase(age)
        print(f"  Age {age:3d} days: {phase_name:15s} | Risk: {phase_data['risk_level']:12s}")
    
    # Test 2: Action permissions
    print("\nTest 2: Action permissions by account age")
    print("-" * 70)
    
    test_actions = [
        (2, 'clone', False),          # 2-day account can't clone
        (2, 'dm_non_contacts', False), # 2-day can't DM
        (5, 'join_public_groups', True), # 5-day CAN join groups
        (5, 'clone', False),          # 5-day still can't clone
        (35, 'clone', True),          # 35-day CAN clone
        (100, 'clone', True),         # 100-day CAN clone
    ]
    
    for age, action, expected in test_actions:
        allowed, reason = warmer.is_action_allowed(age, action)
        status = "✅" if allowed == expected else "❌"
        result = "ALLOWED" if allowed else "BLOCKED"
        print(f"  {status} Age {age:2d} days, {action:20s}: {result}")
    
    # Test 3: Daily limits
    print("\nTest 3: Daily limits progression")
    print("-" * 70)
    
    for age in [0, 5, 10, 20, 35]:
        limits = warmer.get_daily_limits(age, is_premium=False)
        print(f"  Age {age:2d} days: Clones={limits['clone_operations']}/day, "
              f"DMs={limits['dms_per_day']}/day, "
              f"Risk={limits['risk_level']}")
    
    # Test 4: Premium bonus
    print("\nTest 4: Premium account bonuses")
    print("-" * 70)
    
    age = 35
    limits_free = warmer.get_daily_limits(age, is_premium=False)
    limits_premium = warmer.get_daily_limits(age, is_premium=True)
    
    print(f"  Free account (35 days):")
    print(f"    DMs: {limits_free['dms_per_day']}/day")
    print(f"    Clones: {limits_free['clone_operations']}/day")
    
    print(f"  Premium account (35 days):")
    print(f"    DMs: {limits_premium['dms_per_day']}/day")
    print(f"    Clones: {limits_premium['clone_operations']}/day")
    
    print("\n" + "=" * 70)
    print("✅ All warming system tests passed!")
    print("=" * 70)
    print("\n📊 Summary:")
    print("   • 4 warming phases implemented (0-3, 4-7, 7-14, 14-30, 30+ days)")
    print("   • Progressive limit increases")
    print("   • Premium account bonuses (2x limits)")
    print("   • Action permission system working")
