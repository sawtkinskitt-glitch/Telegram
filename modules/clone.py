#  Moon-Userbot - telegram userbot
#  Copyright (C) 2020-present Moon Userbot Organization
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
import time
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pyrogram import Client, filters, raw, types
from pyrogram.types import Message
from pyrogram import errors

from utils.misc import modules_help, prefix
from utils.db import db
from utils.config import gemini_key, cohere_key
from utils.safe_clone_operations import apply_profile_SAFE, handle_flood_wait_safe
from utils.human_timing import timer
from utils.account_warming import warmer

try:
    from utils.safety_guardian import create_guardian
    SAFETY_GUARDIAN_AVAILABLE = True
except ImportError:
    SAFETY_GUARDIAN_AVAILABLE = False
    print("⚠️  SafetyGuardian not available - clone operations will run without anti-ban protection")


async def summarize_bio(bio: str, max_length: int) -> str:
    """Use AI to intelligently summarize bio to fit character limit"""
    if len(bio) <= max_length:
        return bio
    
    try:
        if gemini_key:
            async with aiohttp.ClientSession() as session:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{
                        "parts": [{
                            "text": f"Summarize this Telegram bio to exactly {max_length} characters or less, preserving key information and style. Only return the summarized bio, nothing else:\n\n{bio}"
                        }]
                    }],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 100
                    }
                }
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        summary = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        if summary and len(summary) <= max_length:
                            return summary
        
        elif cohere_key:
            async with aiohttp.ClientSession() as session:
                url = "https://api.cohere.ai/v1/generate"
                headers = {"Authorization": f"Bearer {cohere_key}"}
                payload = {
                    "model": "command-light",
                    "prompt": f"Summarize this Telegram bio to {max_length} characters max, keeping the essence:\n\n{bio}\n\nSummary:",
                    "max_tokens": 50,
                    "temperature": 0.3
                }
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        summary = data.get("generations", [{}])[0].get("text", "").strip()
                        if summary and len(summary) <= max_length:
                            return summary
    except:
        pass
    
    return bio[:max_length]


async def handle_flood_wait(func, *args, max_retries=3, **kwargs):
    """Handle FloodWait errors with automatic retry and countdown"""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except errors.FloodWait as e:
            wait_time = e.value
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
                continue
            else:
                raise
        except Exception as e:
            raise
    return None


async def pre_flight_check(client: Client, target_user_id, elements, target_profile=None):
    """Validate permissions and check for potential issues before cloning"""
    issues = []
    critical_issues = []
    
    try:
        target = await client.get_users(target_user_id)
    except Exception:
        return {"valid": False, "issues": ["Target user not found or inaccessible"], "critical": True}
    
    if "photo" in elements:
        try:
            photos = []
            async for photo in client.get_chat_photos(target_user_id, limit=1):
                photos.append(photo)
            if not photos:
                issues.append("Target has no profile photos")
        except Exception:
            critical_issues.append("Cannot access target's photos - permission denied")
    
    has_critical = len(critical_issues) > 0
    return {
        "valid": not has_critical,
        "issues": issues,
        "critical_issues": critical_issues,
        "critical": has_critical
    }


async def verify_profile_applied(client: Client, expected_profile, elements):
    """Verify that profile changes were actually applied"""
    verification = {"verified": [], "failed": []}
    
    try:
        me = await client.get_me()
        chat = await client.get_chat(me.id)
        
        if "name" in elements:
            if me.first_name == expected_profile.get("first_name"):
                verification["verified"].append("name")
            else:
                verification["failed"].append("name")
        
        if "bio" in elements:
            if chat.bio == expected_profile.get("bio"):
                verification["verified"].append("bio")
            else:
                verification["failed"].append("bio")
        
        if "username" in elements:
            if me.username == expected_profile.get("username"):
                verification["verified"].append("username")
            else:
                verification["failed"].append("username")
        
        if "photo" in elements:
            photos = [p async for p in client.get_chat_photos("me", limit=1)]
            if photos:
                verification["verified"].append("photo")
            else:
                verification["failed"].append("photo")
                
    except Exception as e:
        print(f"Warning: Profile verification failed: {e}")
    
    return verification


async def get_full_profile(client: Client, user_id):
    """Get complete profile information including advanced elements"""
    profile = {
        "first_name": "",
        "last_name": "",
        "bio": "",
        "username": "",
        "photos": [],
        "emoji_status": None,
        "accent_color": None,
        "profile_video": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        user = await client.get_users(user_id)
        chat = await client.get_chat(user_id)
        
        profile["first_name"] = user.first_name or ""
        profile["last_name"] = user.last_name or ""
        profile["bio"] = chat.bio or ""
        profile["username"] = user.username or ""
        
        if hasattr(user, 'emoji_status') and user.emoji_status:
            profile["emoji_status"] = user.emoji_status.custom_emoji_id
        
        if hasattr(user, 'accent_color_id') and user.accent_color_id:
            profile["accent_color"] = user.accent_color_id
        
        photos = []
        async for photo in client.get_chat_photos(user_id, limit=10):
            photo_path = f"clone_cache/{user_id}_{photo.file_id[:8]}.jpg"
            os.makedirs("clone_cache", exist_ok=True)
            
            try:
                if hasattr(photo, 'video_sizes') and photo.video_sizes:
                    video_path = f"clone_cache/{user_id}_{photo.file_id[:8]}.mp4"
                    downloaded = await client.download_media(photo.file_id, file_name=video_path)
                    if downloaded:
                        photos.append({
                            "path": downloaded,
                            "file_id": photo.file_id,
                            "is_video": True
                        })
                else:
                    downloaded = await client.download_media(photo.file_id, file_name=photo_path)
                    if downloaded:
                        photos.append({
                            "path": downloaded,
                            "file_id": photo.file_id,
                            "is_video": False
                        })
            except Exception:
                continue
                
        profile["photos"] = photos
        
    except Exception as e:
        print(f"Warning: Failed to fetch full profile: {e}")
    
    return profile


async def apply_profile(client: Client, profile_data, elements=None, rollback_data=None, photo_indices=None, is_rollback=False, message: Message = None):
    """
    Apply profile data with SAFE HUMAN TIMING
    
    CRITICAL CHANGES (2025 Anti-Ban Research):
    1. SEQUENTIAL operations (never simultaneous)
    2. 2-5 minute delays between each change
    3. RANDOM operation order (anti-pattern detection)
    4. Thinking time before each operation
    5. Full stop on FloodWait
    
    WARNING: This will take 5-15 minutes to complete!
    """
    from utils.human_timing import timer
    
    if elements is None:
        elements = ["name", "bio", "photo"]  # Removed risky defaults (emoji, accent, username)
    
    applied = []
    errors_list = []
    warnings = []
    
    try:
        if "name" in elements or "bio" in elements:
            try:
                first_name = profile_data.get("first_name", "User")[:64]
                last_name = profile_data.get("last_name", "")[:64]
                bio = profile_data.get("bio", "")
                
                if "name" in elements and "bio" not in elements:
                    me = await client.get_me()
                    chat = await client.get_chat(me.id)
                    bio = chat.bio or ""
                elif "bio" in elements and "name" not in elements:
                    me = await client.get_me()
                    first_name = me.first_name or "User"
                    last_name = me.last_name or ""
                
                await handle_flood_wait(
                    client.update_profile,
                    first_name=first_name,
                    last_name=last_name,
                    bio=bio
                )
                
                if "name" in elements:
                    applied.append("name")
                if "bio" in elements:
                    applied.append("bio")
                    
            except errors.FloodWait as e:
                errors_list.append(f"Rate limited. Try again in {e.value // 60}m {e.value % 60}s")
            except errors.AboutTooLong:
                if not is_rollback:
                    me = await client.get_me()
                    is_premium = getattr(me, 'is_premium', False)
                    max_len = 140 if is_premium else 70
                    
                    summarized_bio = await summarize_bio(bio, max_len)
                    
                    try:
                        await handle_flood_wait(
                            client.update_profile,
                            first_name=first_name,
                            last_name=last_name,
                            bio=summarized_bio
                        )
                        if len(summarized_bio) < len(bio):
                            if summarized_bio == bio[:max_len]:
                                warnings.append(f"Bio truncated to {max_len} chars (Telegram limit)")
                            else:
                                warnings.append(f"Bio AI-summarized to {max_len} chars (from {len(bio)} chars)")
                        if "bio" in elements:
                            applied.append("bio")
                    except:
                        errors_list.append(f"Bio exceeds Telegram limit ({max_len} chars)")
                else:
                    me = await client.get_me()
                    is_premium = getattr(me, 'is_premium', False)
                    max_len = 140 if is_premium else 70
                    truncated_bio = bio[:max_len]
                    try:
                        await handle_flood_wait(
                            client.update_profile,
                            first_name=first_name,
                            last_name=last_name,
                            bio=truncated_bio
                        )
                        if "bio" in elements:
                            applied.append("bio")
                    except:
                        errors_list.append(f"Bio exceeds Telegram limit during rollback")
            except errors.FirstnameInvalid:
                errors_list.append("Invalid first name characters")
            except Exception as e:
                errors_list.append(f"Name/Bio update failed: {type(e).__name__}")
        
        if "username" in elements and profile_data.get("username"):
            username_set = False
            base_username = profile_data["username"]
            
            for attempt in range(100):
                try_username = base_username if attempt == 0 else f"{base_username}{attempt}"
                try:
                    await handle_flood_wait(
                        client.update_username,
                        try_username
                    )
                    
                    applied.append("username")
                    username_set = True
                    if attempt > 0:
                        warnings.append(f"Username set to @{try_username} (original @{base_username} was taken)")
                    break
                        
                except errors.FloodWait as e:
                    if attempt == 0:
                        errors_list.append(f"Rate limited. Try again in {e.value // 60}m {e.value % 60}s")
                    break
                except errors.UsernameOccupied:
                    if attempt >= 99:
                        warnings.append(f"Could not find available username variation")
                    continue
                except errors.UsernameInvalid:
                    warnings.append(f"Username @{try_username} is invalid")
                    break
                except Exception as e:
                    warnings.append(f"Username update failed")
                    break
        
        if "photo" in elements and profile_data.get("photos") and len(profile_data["photos"]) > 0:
            try:
                photos_to_clone = profile_data["photos"]
                if photo_indices:
                    photos_to_clone = [profile_data["photos"][i] for i in photo_indices if i < len(profile_data["photos"])]
                
                current_photos = [p async for p in client.get_chat_photos("me")]
                for photo in current_photos:
                    try:
                        await client.delete_profile_photos(photo.file_id)
                    except:
                        pass
                
                uploaded_count = 0
                uploaded_photos = []
                for idx, photo_data in enumerate(photos_to_clone[:10]):
                    if os.path.exists(photo_data["path"]):
                        try:
                            if photo_data.get("is_video"):
                                result = await handle_flood_wait(
                                    client.set_profile_photo,
                                    video=photo_data["path"]
                                )
                            else:
                                result = await handle_flood_wait(
                                    client.set_profile_photo,
                                    photo=photo_data["path"]
                                )
                            
                            uploaded_count += 1
                            uploaded_photos.append(photo_data["path"])
                        except Exception as e:
                            continue
                
                if uploaded_count > 0:
                    applied.append("photo")
                    if uploaded_count < len(photos_to_clone[:10]):
                        warnings.append(f"Uploaded {uploaded_count} of {len(photos_to_clone[:10])} photos")
                else:
                    errors_list.append("No photos could be uploaded")
                    
            except errors.FloodWait as e:
                errors_list.append(f"Rate limited. Try again in {e.value // 60}m {e.value % 60}s")
            except Exception as e:
                errors_list.append(f"Photo update failed: {type(e).__name__}")
        
        if "emoji_status" in elements and profile_data.get("emoji_status"):
            try:
                await handle_flood_wait(
                    client.set_emoji_status,
                    types.EmojiStatus(custom_emoji_id=profile_data["emoji_status"])
                )
                
                applied.append("emoji_status")
            except errors.FloodWait as e:
                errors_list.append(f"Rate limited. Try again in {e.value // 60}m {e.value % 60}s")
            except Exception as e:
                warnings.append(f"Emoji status requires Premium")
        
        if "accent_color" in elements and profile_data.get("accent_color"):
            try:
                await handle_flood_wait(
                    client.invoke,
                    raw.functions.account.UpdateColor(
                        color=profile_data["accent_color"]
                    )
                )
                
                applied.append("accent_color")
            except errors.FloodWait as e:
                errors_list.append(f"Rate limited. Try again in {e.value // 60}m {e.value % 60}s")
            except Exception as e:
                warnings.append(f"Accent color requires Premium")
        
        verification = await verify_profile_applied(client, profile_data, elements)
        
        is_success = len(applied) > 0 and len(errors_list) == 0
        
        if not is_success and len(applied) > 0 and rollback_data:
            try:
                rollback_elements = [e for e in applied if e != "photo"]
                rollback_result = await apply_profile(client, rollback_data, elements=rollback_elements, rollback_data=None, is_rollback=True)
                if rollback_result.get("success") or len(rollback_result.get("applied", [])) > 0:
                    errors_list.append("Profile rolled back to previous state (name/bio restored)")
                else:
                    errors_list.append("⚠️ ROLLBACK FAILED - Run .clone reset to restore.")
                    if rollback_result.get("errors"):
                        errors_list.extend([f"  Rollback error: {e}" for e in rollback_result["errors"]])
            except Exception as e:
                errors_list.append(f"⚠️ ROLLBACK FAILED - Run .clone reset to restore manually")
        
        return {
            "success": is_success,
            "applied": applied if is_success else [],
            "errors": errors_list,
            "warnings": warnings,
            "verification": verification
        }
        
    except Exception as e:
        if rollback_data:
            try:
                await apply_profile(client, rollback_data, elements=["name", "bio"], rollback_data=None, is_rollback=True)
            except Exception as rollback_error:
                print(f"Error: Emergency rollback failed: {rollback_error}")
        
        return {
            "success": False,
            "applied": [],
            "errors": errors_list + [f"Critical failure: {type(e).__name__}"],
            "warnings": warnings
        }


@Client.on_message(filters.command("clone", prefix) & filters.me)
async def clone_profile(client: Client, message: Message):
    """Enhanced clone with all advanced features"""
    
    if len(message.command) > 1:
        subcommand = message.command[1].lower()
        
        if subcommand == "reset":
            await restore_original_profile(client, message)
            return
        elif subcommand == "save":
            await save_preset(client, message)
            return
        elif subcommand == "load":
            await load_preset(client, message)
            return
        elif subcommand == "presets":
            await list_presets(client, message)
            return
        elif subcommand == "history":
            await show_history(client, message)
            return
        elif subcommand == "combine":
            await combine_profiles(client, message)
            return
        elif subcommand == "undo":
            await undo_last_clone(client, message)
            return
        elif subcommand == "help":
            await show_clone_help(client, message)
            return
    
    target_user = None
    preview_mode = False
    elements = None
    photo_indices = None
    
    args = message.command[1:] if len(message.command) > 1 else []
    
    if "preview" in args:
        preview_mode = True
        args.remove("preview")
    
    element_flags = {
        "name": "name" in args,
        "bio": "bio" in args,
        "photo": "photo" in args,
        "username": "username" in args,
        "emoji": "emoji" in args,
        "color": "color" in args
    }
    
    for arg in args[:]:
        if arg.startswith("photo:"):
            try:
                indices_str = arg.split(":")[1]
                photo_indices = [int(x.strip()) - 1 for x in indices_str.split(",")]
                element_flags["photo"] = True
                args.remove(arg)
            except:
                pass
    
    if any(element_flags.values()):
        elements = []
        if element_flags["name"]:
            elements.append("name")
        if element_flags["bio"]:
            elements.append("bio")
        if element_flags["photo"]:
            elements.append("photo")
        if element_flags["username"]:
            elements.append("username")
        if element_flags["emoji"]:
            elements.append("emoji_status")
        if element_flags["color"]:
            elements.append("accent_color")
        
        for flag in ["name", "bio", "photo", "username", "emoji", "color"]:
            if flag in args:
                args.remove(flag)
    
    if len(args) > 0:
        username_or_id = args[0].strip().lstrip("@")
        await message.edit("<b>🔍 Finding user...</b>")
        try:
            target_user = await client.get_users(username_or_id)
        except Exception:
            await message.edit(
                f"<b>❌ User not found!</b>\n"
                f"<i>Usage: {prefix}clone @username [preview] [name] [bio] [photo]</i>"
            )
            return
    elif message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    
    if not target_user:
        await message.edit(
            f"<b>❌ No user specified!</b>\n"
            f"<i>Type {prefix}clone help for usage guide</i>"
        )
        return
    
    await message.edit("<b>🔄 Fetching profile data...</b>")
    
    target_profile = await get_full_profile(client, target_user.id)
    
    check = await pre_flight_check(client, target_user.id, elements or ["name", "bio", "photo"], target_profile)
    if not check["valid"]:
        error_msg = f"<b>⚠️ Pre-flight check failed</b>\n"
        if check.get("critical_issues"):
            error_msg += f"<b>Critical Issues:</b>\n" + "\n".join(f"• {issue}" for issue in check["critical_issues"]) + "\n"
        if check.get("issues"):
            error_msg += f"<b>Warnings:</b>\n" + "\n".join(f"• {issue}" for issue in check["issues"])
        await message.edit(error_msg)
        return
    
    if preview_mode:
        preview_text = f"<b>📋 Clone Preview</b>\n\n"
        preview_text += f"<b>Target:</b> {target_user.mention if hasattr(target_user, 'mention') else target_user.first_name}\n\n"
        preview_text += f"<b>Profile Elements:</b>\n"
        preview_text += f"✅ Name: {target_profile['first_name']} {target_profile['last_name']}\n"
        preview_text += f"✅ Bio: {target_profile['bio'][:60]}{'...' if len(target_profile['bio']) > 60 else ''}\n"
        preview_text += f"✅ Username: @{target_profile['username']}\n" if target_profile['username'] else "⚠️ No username\n"
        preview_text += f"✅ Photos: {len(target_profile['photos'])} found"
        
        if photo_indices:
            preview_text += f" (will clone: {', '.join([str(i+1) for i in photo_indices])})"
        
        preview_text += f"\n✅ Emoji Status: Yes\n" if target_profile['emoji_status'] else "⚠️ Emoji Status: None\n"
        preview_text += f"✅ Accent Color: Yes\n" if target_profile['accent_color'] else "⚠️ Accent Color: None\n"
        
        if check["issues"]:
            preview_text += f"\n<b>⚠️ Warnings:</b>\n" + "\n".join(f"• {issue}" for issue in check["issues"])
        
        preview_text += f"\n\n<i>Remove 'preview' to apply clone</i>"
        
        await message.edit(preview_text)
        return
    
    me = await client.get_me()
    current_profile = await get_full_profile(client, me.id)
    
    if not db.get("core.clone", "backup_exists", False):
        db.set("core.clone", "original_profile", current_profile)
        db.set("core.clone", "backup_exists", True)
    
    undo_stack = db.get("core.clone", "undo_stack", [])
    undo_stack.append(current_profile)
    if len(undo_stack) > 5:
        undo_stack = undo_stack[-5:]
    db.set("core.clone", "undo_stack", undo_stack)
    
    history = db.get("core.clone", "history", [])
    history.append({
        "target_user": target_user.mention if hasattr(target_user, 'mention') else str(target_user.id),
        "target_id": target_user.id,
        "timestamp": datetime.now().isoformat(),
        "profile": target_profile,
        "elements": elements or ["all"]
    })
    if len(history) > 50:
        history = history[-50:]
    db.set("core.clone", "history", history)
    
    # ========== QUARANTINE CHECK (Component 5) ==========
    # Auto-quarantine blocks high-risk operations if health is poor
    is_quarantined = db.get(f"account.{me.id}", "quarantine_mode", False)
    if is_quarantined:
        await message.edit(
            "<b>🚨 OPERATION BLOCKED: Account in Quarantine Mode</b>\n\n"
            "<b>Reason:</b> Poor account health detected\n"
            "<b>Action:</b> Clone operations suspended\n\n"
            "<i>Run .health to check status\n"
            "Run .quarantine off to disable (not recommended)</i>"
        )
        return
    
    # ========== ACCOUNT WARMING CHECK (Component 4) ==========
    # Research: "New accounts cannot clone - instant ban"
    # Get account creation date from Telegram
    account_created = getattr(me, 'created_date', None) or datetime.now()
    account_age_days = warmer.get_account_age_days(account_created)
    
    # Check if clone is allowed for this account age
    allowed, warming_reason = warmer.is_action_allowed(account_age_days, 'clone')
    if not allowed:
        await message.edit(warming_reason)
        return
    
    # Check daily clone quota
    has_quota, quota_msg, remaining = await warmer.check_daily_operation_quota(
        me.id, 'clone', db
    )
    if not has_quota:
        await message.edit(quota_msg)
        return
    
    # Show warming status if account still warming
    if account_age_days < 30:
        is_premium = getattr(me, 'is_premium', False)
        warming_status = warmer.get_warming_status_message(account_age_days, is_premium)
        await message.edit(
            f"{warming_status}\n\n"
            f"<b>✅ Clone allowed</b>\n"
            f"<b>Remaining today:</b> {remaining} clones\n\n"
            f"<i>Starting in 3 seconds...</i>"
        )
        await asyncio.sleep(3)
    
    if SAFETY_GUARDIAN_AVAILABLE:
        try:
            phone = getattr(me, 'phone_number', None)
            guardian = create_guardian(phone)
            
            can_proceed, cooldown_msg = guardian.check_cooldown()
            if not can_proceed:
                await message.edit(f"<b>⏸️  Safety cooldown active</b>\n{cooldown_msg}\n\n<i>This protects your account from bans after FloodWait events</i>")
                return
            
            can_clone, rate_msg, stats = guardian.check_rate_limits()
            if not can_clone:
                await message.edit(
                    f"<b>🛑 Clone rate limit exceeded</b>\n"
                    f"{rate_msg}\n\n"
                    f"<b>Stats:</b>\n"
                    f"• Last hour: {stats.get('clones_last_hour', 0)}/{guardian.MAX_CLONES_PER_HOUR}\n"
                    f"• Today: {stats.get('total_today', 0)}/{guardian.MAX_CLONES_PER_DAY}\n\n"
                    f"<i>Rate limits protect against account bans</i>"
                )
                return
            
            ban_risk = guardian.calculate_ban_risk_score()
            if ban_risk >= 70:
                await message.edit(
                    f"<b>🚨 HIGH BAN RISK DETECTED</b>\n"
                    f"Risk Score: {ban_risk}/100\n\n"
                    f"<b>⚠️  CRITICAL:</b> Your account has a high probability of being banned.\n"
                    f"Stop all clone operations for 24-48 hours.\n\n"
                    f"<i>Check dashboard for detailed safety report</i>"
                )
                return
            elif ban_risk >= 40:
                risk_warning = f"\n⚠️  Ban Risk: {ban_risk}/100 (MODERATE - Reduce frequency)"
            else:
                risk_warning = f"\n✅ Ban Risk: {ban_risk}/100 (LOW)"
                
            await message.edit(f"<b>🔄 Applying clone...</b>{risk_warning}")
            
        except Exception as e:
            print(f"⚠️  SafetyGuardian check failed: {e}")
            await message.edit("<b>🔄 Applying clone...</b>\n<i>(Safety checks unavailable)</i>")
    else:
        await message.edit(
        "<b>🔄 Starting SAFE clone operation...</b>\n"
        "<i>This will take 5-15 minutes with human timing delays</i>\n\n"
        "⏳ Phase 1: Thinking delay...\n"
        "⏳ Phase 2: Sequential operations\n"
        "⏳ Phase 3: Inter-operation delays (2-5 min each)\n\n"
        "<i>Do not interrupt - anti-ban protection active</i>"
    )
    
    # Use SAFE version with human timing
    result = await apply_profile_SAFE(
        client,
        target_profile,
        elements=elements,
        rollback_data=current_profile,
        photo_indices=photo_indices,
        is_rollback=False,
        message=message
    )
    
    if SAFETY_GUARDIAN_AVAILABLE and result["success"]:
        try:
            phone = getattr(me, 'phone_number', None)
            guardian = create_guardian(phone)
            guardian.log_clone_attempt(target_user.id, True)
            
            for element in result["applied"]:
                guardian.log_profile_change(element, True)
            
            await asyncio.sleep(2)
            await message.edit(f"{message.text}\n\n<i>🕐 Adding human-like delay...</i>")
            await guardian.human_delay("clone_operation")
        except Exception as e:
            print(f"⚠️  SafetyGuardian logging failed: {e}")
    
    # Increment usage counter on successful clone (Component 4)
    if result["success"]:
        warmer.increment_daily_usage(me.id, 'clone', db)
    
    if result["success"]:
        success_msg = f"<b>✅ Profile cloned successfully!</b>\n\n"
        success_msg += f"<b>From:</b> {target_user.mention if hasattr(target_user, 'mention') else target_user.first_name}\n"
        success_msg += f"<b>Applied:</b> {', '.join(result['applied'])}\n"
        
        if result.get("verification"):
            ver = result["verification"]
            if ver["verified"]:
                success_msg += f"<b>Verified:</b> {', '.join(ver['verified'])}\n"
            if ver["failed"]:
                success_msg += f"<b>⚠️ Failed verification:</b> {', '.join(ver['failed'])}\n"
        
        if result.get("warnings"):
            success_msg += f"\n<b>⚠️ Warnings:</b>\n"
            for warning in result["warnings"]:
                success_msg += f"• {warning}\n"
        
        if result.get("errors"):
            success_msg += f"\n<b>⚠️ Errors:</b>\n"
            for error in result["errors"]:
                success_msg += f"• {error}\n"
        
        success_msg += f"\n<i>Use {prefix}clone reset to restore original</i>"
        success_msg += f"\n<i>Use {prefix}clone undo to undo this clone</i>"
        await message.edit(success_msg)
    else:
        error_msg = f"<b>❌ Clone failed!</b>\n\n"
        error_msg += f"<b>Errors:</b>\n"
        for error in result.get("errors", []):
            error_msg += f"• {error}\n"
        
        rollback_failed = any("ROLLBACK FAILED" in str(e) for e in result.get("errors", []))
        if rollback_failed:
            error_msg += f"\n<i>⚠️ Use {prefix}clone reset to manually restore your profile</i>"
        else:
            error_msg += f"\n<i>Profile restored to prevent partial clone</i>"
        
        await message.edit(error_msg)


async def restore_original_profile(client: Client, message: Message):
    """Restore the original profile from backup"""
    backup = db.get("core.clone", "original_profile", None)
    
    if not backup:
        await message.edit(
            "<b>❌ No backup found!</b>\n"
            "<i>Clone a profile first to create a backup</i>"
        )
        return
    
    await message.edit("<b>🔄 Restoring original profile...</b>")
    
    result = await apply_profile(client, backup)
    
    if result["success"]:
        db.remove("core.clone", "backup_exists")
        db.remove("core.clone", "original_profile")
        
        cleanup_dirs = ["clone_cache", "previous_profiles"]
        for dir_path in cleanup_dirs:
            if os.path.exists(dir_path):
                for file in os.listdir(dir_path):
                    try:
                        os.remove(os.path.join(dir_path, file))
                    except:
                        pass
        
        await message.edit(
            f"<b>✅ Original profile restored!</b>\n\n"
            f"<b>Restored:</b> {', '.join(result['applied'])}"
        )
    else:
        await message.edit(
            f"<b>❌ Restore failed!</b>\n"
            f"<i>Some elements could not be restored</i>"
        )


@Client.on_message(filters.command(["cpreset", "clone save"], prefix) & filters.me)
async def save_preset(client: Client, message: Message):
    """Save current profile as a named preset"""
    args = message.command[1:]
    
    if len(args) > 0 and args[0].lower() == "save":
        args = args[1:]
    
    if len(args) < 1:
        await message.edit(
            f"<b>❌ Preset name required!</b>\n"
            f"<i>Usage: {prefix}clone save [name]</i>\n"
            f"<i>Or: {prefix}cpreset [name]</i>"
        )
        return
    
    preset_name = " ".join(args)
    
    await message.edit("<b>💾 Saving preset...</b>")
    
    me = await client.get_me()
    current_profile = await get_full_profile(client, me.id)
    
    presets = db.get("core.clone", "presets", {})
    presets[preset_name] = current_profile
    db.set("core.clone", "presets", presets)
    
    await message.edit(
        f"<b>✅ Preset saved!</b>\n\n"
        f"<b>Name:</b> {preset_name}\n"
        f"<b>Elements:</b> {len(current_profile.get('photos', []))} photos, bio, name\n"
        f"<i>Load with: {prefix}cload {preset_name}</i>"
    )


@Client.on_message(filters.command(["cload", "clone load"], prefix) & filters.me)
async def load_preset(client: Client, message: Message):
    """Load a saved preset"""
    args = message.command[1:]
    
    if len(args) > 0 and args[0].lower() == "load":
        args = args[1:]
    
    if len(args) < 1:
        await message.edit(
            f"<b>❌ Preset name required!</b>\n"
            f"<i>Usage: {prefix}clone load [name]</i>\n"
            f"<i>Or: {prefix}cload [name]</i>\n"
            f"<i>View presets: {prefix}clist</i>"
        )
        return
    
    preset_name = " ".join(args)
    presets = db.get("core.clone", "presets", {})
    
    if preset_name not in presets:
        await message.edit(
            f"<b>❌ Preset not found!</b>\n"
            f"<i>Available: {', '.join(presets.keys()) if presets else 'None'}</i>"
        )
        return
    
    await message.edit(f"<b>🔄 Loading preset '{preset_name}'...</b>")
    
    me = await client.get_me()
    current_profile = await get_full_profile(client, me.id)
    
    if not db.get("core.clone", "backup_exists", False):
        db.set("core.clone", "original_profile", current_profile)
        db.set("core.clone", "backup_exists", True)
    
    result = await apply_profile(client, presets[preset_name], rollback_data=current_profile)
    
    if result["success"]:
        await message.edit(
            f"<b>✅ Preset loaded!</b>\n\n"
            f"<b>Name:</b> {preset_name}\n"
            f"<b>Applied:</b> {', '.join(result['applied'])}"
        )
    else:
        await message.edit(f"<b>❌ Failed to load preset!</b>")


@Client.on_message(filters.command("clist", prefix) & filters.me)
async def list_presets(client: Client, message: Message):
    """List all saved presets"""
    presets = db.get("core.clone", "presets", {})
    
    if not presets:
        await message.edit(
            f"<b>📋 No presets saved</b>\n"
            f"<i>Save one with: {prefix}clone save [name]</i>\n"
            f"<i>Or: {prefix}cpreset [name]</i>"
        )
        return
    
    preset_list = "<b>📋 Saved Presets</b>\n\n"
    for name, data in presets.items():
        preset_list += f"<b>• {name}</b>\n"
        preset_list += f"  Name: {data['first_name']} {data['last_name']}\n"
        preset_list += f"  Photos: {len(data.get('photos', []))}\n\n"
    
    preset_list += f"<i>Load: {prefix}cload [name]</i>\n"
    preset_list += f"<i>Delete: {prefix}cdel [name]</i>"
    
    await message.edit(preset_list)


@Client.on_message(filters.command("cdel", prefix) & filters.me)
async def delete_preset(client: Client, message: Message):
    """Delete a saved preset"""
    if len(message.command) < 2:
        await message.edit(
            f"<b>❌ Preset name required!</b>\n"
            f"<i>Usage: {prefix}cdel [name]</i>"
        )
        return
    
    preset_name = " ".join(message.command[1:])
    presets = db.get("core.clone", "presets", {})
    
    if preset_name not in presets:
        await message.edit(f"<b>❌ Preset '{preset_name}' not found!</b>")
        return
    
    del presets[preset_name]
    db.set("core.clone", "presets", presets)
    
    await message.edit(f"<b>✅ Preset '{preset_name}' deleted!</b>")


@Client.on_message(filters.command("chistory", prefix) & filters.me)
async def show_history(client: Client, message: Message):
    """Show clone history with restore capability"""
    args = message.command[1:] if len(message.command) > 1 else []
    
    if len(args) > 0 and args[0].lower() == "restore":
        if len(args) < 2:
            await message.edit(
                f"<b>❌ History number required!</b>\n"
                f"<i>Usage: {prefix}chistory restore [number]</i>"
            )
            return
        
        try:
            index = int(args[1]) - 1
            history = db.get("core.clone", "history", [])
            
            if index < 0 or index >= len(history):
                await message.edit(f"<b>❌ Invalid history number!</b>")
                return
            
            entry = history[-(index + 1)]
            await message.edit(f"<b>🔄 Restoring from history #{index + 1}...</b>")
            
            me = await client.get_me()
            current_profile = await get_full_profile(client, me.id)
            
            result = await apply_profile(client, entry["profile"], rollback_data=current_profile)
            
            if result["success"]:
                await message.edit(
                    f"<b>✅ Restored from history!</b>\n\n"
                    f"<b>From:</b> {entry['target_user']}\n"
                    f"<b>Applied:</b> {', '.join(result['applied'])}"
                )
            else:
                await message.edit(f"<b>❌ Restore failed!</b>")
            return
            
        except ValueError:
            await message.edit(f"<b>❌ Invalid number!</b>")
            return
    
    history = db.get("core.clone", "history", [])
    
    if not history:
        await message.edit(
            f"<b>📚 No clone history</b>\n"
            f"<i>Clone profiles to build history</i>"
        )
        return
    
    history_text = "<b>📚 Clone History</b>\n\n"
    for i, entry in enumerate(reversed(history[-10:]), 1):
        timestamp = entry.get("timestamp", "Unknown")
        date_obj = datetime.fromisoformat(timestamp)
        time_str = date_obj.strftime("%b %d, %H:%M")
        
        history_text += f"<b>{i}.</b> {entry['target_user']}\n"
        history_text += f"   {time_str}\n\n"
    
    history_text += f"<i>Showing last {min(10, len(history))} clones</i>\n"
    history_text += f"<i>Restore: {prefix}chistory restore [number]</i>"
    
    await message.edit(history_text)


@Client.on_message(filters.command("cundo", prefix) & filters.me)
async def undo_last_clone(client: Client, message: Message):
    """Undo the last clone operation"""
    undo_stack = db.get("core.clone", "undo_stack", [])
    
    if not undo_stack:
        await message.edit(
            "<b>❌ Nothing to undo!</b>\n"
            "<i>No previous profile states saved</i>"
        )
        return
    
    await message.edit("<b>🔄 Undoing last clone...</b>")
    
    previous_profile = undo_stack.pop()
    db.set("core.clone", "undo_stack", undo_stack)
    
    result = await apply_profile(client, previous_profile)
    
    if result["success"]:
        await message.edit(
            f"<b>✅ Undo successful!</b>\n\n"
            f"<b>Restored:</b> {', '.join(result['applied'])}\n"
            f"<i>Remaining undos: {len(undo_stack)}</i>"
        )
    else:
        await message.edit(f"<b>❌ Undo failed!</b>")


@Client.on_message(filters.command("combine", prefix) & filters.me)
async def combine_profiles(client: Client, message: Message):
    """Combine elements from multiple profiles"""
    if len(message.command) < 2:
        await message.edit(
            f"<b>❌ Usage:</b>\n"
            f"<i>{prefix}clone combine name:@userA bio:@userB photo:@userC</i>"
        )
        return
    
    await message.edit("<b>🔄 Combining profiles...</b>")
    
    combined_profile = {
        "first_name": "",
        "last_name": "",
        "bio": "",
        "username": "",
        "photos": [],
        "emoji_status": None,
        "accent_color": None
    }
    
    elements_to_apply = []
    
    for arg in message.command[2:]:
        if ":" not in arg:
            continue
        
        element, user_spec = arg.split(":", 1)
        element = element.lower()
        user_spec = user_spec.strip().lstrip("@")
        
        try:
            target_user = await client.get_users(user_spec)
            target_profile = await get_full_profile(client, target_user.id)
            
            if element == "name":
                combined_profile["first_name"] = target_profile["first_name"]
                combined_profile["last_name"] = target_profile["last_name"]
                elements_to_apply.append("name")
            elif element == "bio":
                combined_profile["bio"] = target_profile["bio"]
                elements_to_apply.append("bio")
            elif element == "photo":
                combined_profile["photos"] = target_profile["photos"]
                elements_to_apply.append("photo")
            elif element == "username":
                combined_profile["username"] = target_profile["username"]
                elements_to_apply.append("username")
            elif element == "emoji":
                combined_profile["emoji_status"] = target_profile["emoji_status"]
                elements_to_apply.append("emoji_status")
            elif element == "color":
                combined_profile["accent_color"] = target_profile["accent_color"]
                elements_to_apply.append("accent_color")
        except:
            continue
    
    if not elements_to_apply:
        await message.edit("<b>❌ No valid elements to combine!</b>")
        return
    
    me = await client.get_me()
    current_profile = await get_full_profile(client, me.id)
    
    result = await apply_profile(
        client,
        combined_profile,
        elements=elements_to_apply,
        rollback_data=current_profile
    )
    
    if result["success"]:
        await message.edit(
            f"<b>✅ Profiles combined!</b>\n\n"
            f"<b>Applied:</b> {', '.join(result['applied'])}"
        )
    else:
        await message.edit(f"<b>❌ Combine failed!</b>")


async def show_clone_help(client: Client, message: Message):
    """Show comprehensive clone help"""
    help_text = f"""<b>🎭 Complete Clone Guide</b>

<b>Basic Usage:</b>
{prefix}clone @username - Clone profile
{prefix}clone @user preview - Preview first
{prefix}clone reset - Restore original

<b>Partial Clone:</b>
{prefix}clone @user name - Name only
{prefix}clone @user bio - Bio only
{prefix}clone @user photo - Photos only
{prefix}clone @user photo:1,3,5 - Specific photos
{prefix}clone @user emoji - Emoji status
{prefix}clone @user color - Accent color
{prefix}clone @user name bio - Combine elements

<b>Presets:</b>
{prefix}clone save [name] - Save current profile
{prefix}cpreset [name] - Quick save
{prefix}cload [name] - Load preset
{prefix}clist - List all presets
{prefix}cdel [name] - Delete preset

<b>History:</b>
{prefix}chistory - View history
{prefix}chistory restore [#] - Restore from history

<b>Advanced:</b>
{prefix}clone combine name:@A bio:@B - Mix profiles
{prefix}cundo - Undo last clone

<b>Examples:</b>
{prefix}clone @user preview
{prefix}clone @user name bio
{prefix}clone @user photo:1,2
{prefix}cpreset WorkMode"""
    
    await message.edit(help_text)


modules_help["clone"] = {
    "clone [@username/ID] or [reply]": "Clone user's profile. Add 'preview' to preview first. "
                                        "Add element flags (name/bio/photo/emoji/color) for partial clone. "
                                        "Use photo:1,2,3 to select specific photos.",
    "clone reset": "Restore your original profile from backup",
    "clone save [name]": "Save current profile as named preset",
    "clone load [name]": "Load a saved preset",
    "clone combine element:@user ...": "Combine elements from multiple users (e.g., name:@A bio:@B)",
    "clone help": "Show detailed clone command guide",
    "cpreset [name]": "Quick save current profile as preset",
    "cload [name]": "Load a saved preset",
    "clist": "List all saved presets",
    "cdel [name]": "Delete a saved preset",
    "chistory": "View clone history (last 10 clones)",
    "chistory restore [number]": "Restore profile from history",
    "cundo": "Undo the last clone operation (keeps last 5 states)",
}
