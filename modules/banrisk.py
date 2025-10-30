"""
Ban Risk Check Command

Provides quick ban risk assessment
"""

from pyrogram import Client, filters
from pyrogram.types import Message
from utils.misc import modules_help, prefix
from utils.ban_risk_calculator import risk_calculator
from utils.account_warming import warmer
from utils.db import db


@Client.on_message(filters.me & filters.command("banrisk", prefix))
async def ban_risk_check(client: Client, message: Message):
    """
    Calculate current ban risk score
    
    Usage:
        .banrisk - Full ban risk assessment
    """
    await message.edit("<b>🔄 Calculating ban risk...</b>")
    
    me = await client.get_me()
    account_id = me.id
    
    # Get account metadata
    account_created = getattr(me, 'created_date', None) or __import__('datetime').datetime.now()
    account_age_days = warmer.get_account_age_days(account_created)
    is_premium = getattr(me, 'is_premium', False)
    
    # Calculate ban risk
    risk_score, risk_level, details = risk_calculator.calculate_ban_risk_score(
        db,
        account_id,
        account_age_days,
        is_premium
    )
    
    # Format report
    report = risk_calculator.format_risk_report(risk_score, risk_level, details)
    
    # Save to database
    db.set(f"account.{account_id}", "last_ban_risk_check", {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "details": details,
        "checked_at": __import__('datetime').datetime.now().isoformat()
    })
    
    await message.edit(report)


# Register command
modules_help["banrisk"] = {
    "banrisk": "Calculate current account ban risk score (research-based formula)"
}
