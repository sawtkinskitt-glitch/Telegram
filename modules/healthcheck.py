"""
Account Health Check Command

Provides commands to:
- Check account health status
- View shadow ban risk
- Get recommendations

Usage:
    .health - Full health report
    .health quick - Quick status
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from utils.misc import modules_help, prefix
from utils.shadowban_detector import detector
from utils.ban_risk_calculator import risk_calculator
from utils.account_warming import warmer
from utils.db import db


@Client.on_message(filters.me & filters.command("health", prefix))
async def health_check(client: Client, message: Message):
    """
    Check account health status
    
    Usage:
        .health - Full comprehensive check (includes @spambot)
        .health quick - Quick anomaly analysis only
    """
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    quick_mode = 'quick' in args
    
    me = await client.get_me()
    account_id = me.id
    
    if quick_mode:
        # Quick mode: Just anomaly analysis (no @spambot)
        await message.edit("<b>🔄 Running quick health check...</b>")
        
        anomaly_analysis = detector.analyze_operation_logs(db, account_id, hours=24)
        
        report = "<b>⚡ Quick Health Check</b>\n\n"
        report += f"<b>Anomaly Analysis (24h):</b>\n"
        report += f"{anomaly_analysis['message']}\n\n"
        report += f"• Score: {anomaly_analysis.get('anomaly_score', 0)}/100\n"
        report += f"• Operations: {anomaly_analysis.get('total_operations', 0)}\n"
        report += f"• FloodWaits: {anomaly_analysis.get('floodwaits', 0)}\n"
        report += f"• Failures: {anomaly_analysis.get('failures', 0)}/{anomaly_analysis.get('total_operations', 0)}\n"
        report += f"• Failure rate: {anomaly_analysis.get('failure_rate', '0%')}\n"
        
        if anomaly_analysis.get('anomaly_reasons'):
            report += f"\n<b>⚠️ Issues:</b>\n"
            for reason in anomaly_analysis['anomaly_reasons']:
                report += f"• {reason}\n"
        
        if anomaly_analysis.get('anomaly_score', 0) >= 70:
            report += f"\n<b>🚨 WARNING:</b> High anomaly score!\n"
            report += f"<i>Run .health for full check including @spambot</i>"
        else:
            report += f"\n<i>Use .health for comprehensive check</i>"
        
        await message.edit(report)
    
    else:
        # Full mode: Complete health check
        await message.edit(
            "<b>🔄 Running full health check...</b>\n\n"
            "<i>Step 1/2: Checking @spambot status...\n"
            "(This may take 5-10 seconds)</i>"
        )
        
        # Run full health check
        health_data = await detector.full_health_check(client, db, account_id)
        
        # Save to database
        db.set(f"account.{account_id}", "last_health_check", health_data)
        
        # Format report
        report = detector.format_health_report(health_data)
        
        # Add quarantine notice if needed
        if health_data['should_quarantine']:
            # Auto-enable quarantine mode
            db.set(f"account.{account_id}", "quarantine_mode", True)
            db.set(f"account.{account_id}", "quarantine_started", health_data['checked_at'])
            
            report += f"\n\n<b>🚨 AUTO-QUARANTINE ACTIVATED</b>\n"
            report += f"<i>All high-risk operations blocked for 48 hours</i>"
        
        await message.edit(report)


@Client.on_message(filters.me & filters.command("quarantine", prefix))
async def quarantine_control(client: Client, message: Message):
    """
    Manually control quarantine mode
    
    Usage:
        .quarantine on - Enable quarantine (blocks high-risk ops)
        .quarantine off - Disable quarantine
        .quarantine status - Check quarantine status
    """
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    if not args:
        args = ['status']
    
    me = await client.get_me()
    account_id = me.id
    
    action = args[0].lower()
    
    if action == 'on':
        db.set(f"account.{account_id}", "quarantine_mode", True)
        db.set(f"account.{account_id}", "quarantine_started", None)  # Manual, no timestamp
        
        await message.edit(
            "<b>🚨 Quarantine Mode: ENABLED</b>\n\n"
            "<b>Blocked operations:</b>\n"
            "• Clone\n"
            "• Mass DM\n"
            "• Spam\n"
            "• Profile changes\n"
            "• Username changes\n\n"
            "<i>Use .quarantine off to disable</i>"
        )
    
    elif action == 'off':
        db.set(f"account.{account_id}", "quarantine_mode", False)
        db.remove(f"account.{account_id}", "quarantine_started")
        
        await message.edit(
            "<b>✅ Quarantine Mode: DISABLED</b>\n\n"
            "<i>High-risk operations now allowed</i>\n"
            "<i>⚠️ Use with caution - run .health first!</i>"
        )
    
    elif action == 'status':
        is_quarantined = db.get(f"account.{account_id}", "quarantine_mode", False)
        started = db.get(f"account.{account_id}", "quarantine_started")
        
        if is_quarantined:
            report = "<b>🚨 Quarantine Mode: ACTIVE</b>\n\n"
            
            if started:
                from datetime import datetime, timedelta
                started_dt = datetime.fromisoformat(started)
                elapsed = datetime.now() - started_dt
                remaining = timedelta(hours=48) - elapsed
                
                if remaining.total_seconds() > 0:
                    hours_remaining = remaining.total_seconds() / 3600
                    report += f"<b>Started:</b> {started_dt.strftime('%Y-%m-%d %H:%M')}\n"
                    report += f"<b>Time remaining:</b> {hours_remaining:.1f} hours\n\n"
                else:
                    report += f"<b>48-hour quarantine completed!</b>\n"
                    report += f"<i>Run .health to verify before disabling</i>\n\n"
            else:
                report += f"<b>Type:</b> Manual quarantine\n\n"
            
            report += f"<b>Blocked operations:</b> Clone, Mass DM, Spam, Profile changes\n\n"
            report += f"<i>Use .quarantine off to disable</i>"
        else:
            report = "<b>✅ Quarantine Mode: INACTIVE</b>\n\n"
            report += f"<i>All operations allowed</i>"
        
        await message.edit(report)
    
    else:
        await message.edit(
            f"<b>❌ Unknown action: {action}</b>\n\n"
            f"<b>Usage:</b>\n"
            f"{prefix}quarantine on - Enable\n"
            f"{prefix}quarantine off - Disable\n"
            f"{prefix}quarantine status - Check status"
        )


# Register commands
modules_help["health"] = {
    "health": "Full account health check (includes @spambot)",
    "health quick": "Quick health check (anomaly analysis only)",
    "quarantine [on/off/status]": "Control quarantine mode (blocks high-risk operations)"
}
