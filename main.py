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

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pip",
#     "pyrofork",
#     "tgcrypto",
#     "wheel",
#     "gunicorn",
#     "flask",
#     "humanize",
#     "pygments",
#     "pymongo",
#     "psutil",
#     "Pillow>=10.3.0",
#     "click",
#     "dnspython",
#     "requests",
#     "environs",
#     "GitPython",
#     "beautifulsoup4",
#     "aiohttp",
#     "aiofiles",
#     "pySmartDL",
# ]
# ///
import logging
import os
import platform
import sqlite3
import subprocess
import sys
import fcntl

import requests
from pyrogram import Client, errors, idle
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.raw.functions.account import DeleteAccount, GetAuthorizations

from utils import config
from utils.db import db
from db_manager import AccountManager
from encryption_service import EncryptionService
from utils.misc import gitrepo, userbot_version
from utils.module import ModuleManager
from utils.rentry import rentry_cleanup_job
from utils.scripts import restart
from utils.device_fingerprints import get_fingerprint_for_account

SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_PATH != os.getcwd():
    os.chdir(SCRIPT_PATH)

# Singleton lock to prevent multiple instances
LOCK_FILE = "/tmp/moonuserbot_instance.lock"
lock_fd = None

def acquire_singleton_lock():
    """Ensure only one instance of the userbot is running"""
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logging.info("✅ Singleton lock acquired (PID: %s)", os.getpid())
        return True
    except IOError:
        logging.error("❌ Another instance is already running! Exiting to prevent AUTH_KEY_DUPLICATED.")
        logging.error("   If you're sure no other instance is running, delete: %s", LOCK_FILE)
        return False

def release_singleton_lock():
    """Release the singleton lock"""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            os.remove(LOCK_FILE)
            logging.info("🔓 Singleton lock released")
        except Exception as e:
            logging.debug("Lock cleanup error (non-critical): %s", e)

# Resolve session credentials
ACCOUNT_SOURCE = "config"
PRIMARY_ACCOUNT = None
PRIMARY_ACCOUNT_ID = None
USING_DB_SESSION = False

session_string = None
api_id_value = config.api_id
api_hash_value = config.api_hash
account_id = None

try:
    PRIMARY_ACCOUNT = AccountManager.get_primary_account()
    if not PRIMARY_ACCOUNT:
        PRIMARY_ACCOUNT = AccountManager.get_recent_account()
except Exception as lookup_error:
    print(f"⚠️  Could not fetch account information from database: {lookup_error}")
    PRIMARY_ACCOUNT = None

if PRIMARY_ACCOUNT:
    try:
        encryptor = EncryptionService()
        decrypted_session = (
            encryptor.decrypt(PRIMARY_ACCOUNT['session_encrypted'])
            if PRIMARY_ACCOUNT.get('session_encrypted')
            else None
        )
        decrypted_api_hash = (
            encryptor.decrypt(PRIMARY_ACCOUNT['api_hash_encrypted'])
            if PRIMARY_ACCOUNT.get('api_hash_encrypted')
            else None
        )
        if decrypted_session:
            session_string = decrypted_session
            api_id_value = PRIMARY_ACCOUNT.get('api_id') or config.api_id
            api_hash_value = decrypted_api_hash or config.api_hash
            PRIMARY_ACCOUNT_ID = PRIMARY_ACCOUNT['id']
            account_id = PRIMARY_ACCOUNT_ID
            USING_DB_SESSION = True
            ACCOUNT_SOURCE = "database"
            db.set("core.session", "account_id", account_id)
        else:
            print("⚠️  Primary account found but session data is missing; falling back to environment STRINGSESSION.")
    except Exception as decrypt_error:
        print(f"⚠️  Failed to decrypt stored session: {decrypt_error}")

if session_string is None and config.STRINGSESSION:
    session_string = config.STRINGSESSION
    if account_id is None:
        account_id = db.get("core.session", "account_id", 1)

if session_string is None:
    raise SystemExit(
        "No session string available. Add an account via the web dashboard or configure STRINGSESSION."
    )

if account_id is None:
    account_id = db.get("core.session", "account_id", 1)

# Get realistic device fingerprint (CRITICAL: hides automation signature)
fingerprint = get_fingerprint_for_account(account_id)

common_params = {
    "api_id": api_id_value,
    "api_hash": api_hash_value,
    "hide_password": True,
    "workdir": SCRIPT_PATH,
    
    # ✅ REALISTIC FINGERPRINT (looks like official Telegram client)
    "device_model": fingerprint['device_model'],
    "system_version": fingerprint['system_version'],
    "app_version": fingerprint['app_version'],
    "lang_code": fingerprint.get('lang_code', 'en'),
    "system_lang_code": fingerprint.get('system_lang_code', 'en-US'),
    
    "sleep_threshold": 30,
    "test_mode": config.test_server,
    "parse_mode": ParseMode.HTML,
}

common_params["session_string"] = session_string
common_params["in_memory"] = True

app = Client("my_account", **common_params)


def load_missing_modules():
    all_modules = db.get("custom.modules", "allModules", [])
    if not all_modules:
        return

    custom_modules_path = f"{SCRIPT_PATH}/modules/custom_modules"
    os.makedirs(custom_modules_path, exist_ok=True)

    try:
        f = requests.get(
            "https://raw.githubusercontent.com/The-MoonTg-project/custom_modules/main/full.txt"
        ).text
    except Exception:
        logging.error("Failed to fetch custom modules list")
        return
    modules_dict = {
        line.split("/")[-1].split()[0]: line.strip() for line in f.splitlines()
    }

    for module_name in all_modules:
        module_path = f"{custom_modules_path}/{module_name}.py"
        if not os.path.exists(module_path) and module_name in modules_dict:
            url = f"https://raw.githubusercontent.com/The-MoonTg-project/custom_modules/main/{modules_dict[module_name]}.py"
            resp = requests.get(url)
            if resp.ok:
                with open(module_path, "wb") as f:
                    f.write(resp.content)
                logging.info("Loaded missing module: %s", module_name)
            else:
                logging.warning("Failed to load module: %s", module_name)


async def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("moonlogs.txt"), logging.StreamHandler()],
        level=logging.INFO,
    )
    
    # Acquire singleton lock to prevent multiple instances
    if not acquire_singleton_lock():
        raise SystemExit(3)  # Exit code 3 for "already running"
    
    DeleteAccount.__new__ = None

    logging.info(
        "Using %s session (account id: %s)",
        ACCOUNT_SOURCE,
        account_id,
    )
    
    # Initialize distributed lock manager
    from distributed_lock_manager import DistributedLockManager
    lock_manager = DistributedLockManager(account_id)
    
    # Acquire distributed lock to prevent AUTH_KEY_DUPLICATED
    logging.info("🔒 Acquiring distributed session lock...")
    if not lock_manager.acquire_lock(timeout=30):
        logging.error("❌ Could not acquire distributed lock - another instance is using this session")
        logging.error("   This prevents AUTH_KEY_DUPLICATED errors")
        logging.error("   If you're sure no other instance is running, wait 5 minutes and try again")
        release_singleton_lock()
        raise SystemExit(4)  # Exit code 4 for "lock timeout"
    
    logging.info("✅ Distributed lock acquired successfully")

    try:
        await app.start()
    except sqlite3.OperationalError as e:
        if str(e) == "database is locked" and os.name == "posix":
            logging.warning(
                "Session file is locked. Trying to kill blocking process..."
            )
            subprocess.run(["fuser", "-k", "my_account.session"], check=True)
            restart()
        raise
    except errors.AuthKeyDuplicated as e:
        logging.error(
            "AUTH_KEY_DUPLICATED: %s\n"
            "This session is being used simultaneously elsewhere (another server/device).\n"
            "Possible causes:\n"
            "  1. Old deployment still running with same session\n"
            "  2. Session being used on another device\n"
            "  3. Multiple instances of this bot running\n"
            "Solution: Stop all other instances and wait 30 seconds before restarting.",
            e,
        )
        
        if USING_DB_SESSION and PRIMARY_ACCOUNT_ID:
            try:
                AccountManager.clear_account_session(PRIMARY_ACCOUNT_ID, status="auth_key_duplicated")
                logging.error(
                    "Cleared stored session for account ID %s due to duplicate auth key.",
                    PRIMARY_ACCOUNT_ID,
                )
            except Exception as cleanup_error:
                logging.error("Failed to clear account session: %s", cleanup_error)
            logging.error(
                "Primary account session is no longer valid. Re-authenticate the account via the dashboard."
            )
            lock_manager.release_lock()
            release_singleton_lock()
            raise SystemExit(2)  # Exit code 2 for auth_key_duplicated
        
        lock_manager.release_lock()
        release_singleton_lock()
        raise SystemExit(2)
    except (errors.NotAcceptable, errors.Unauthorized) as e:
        logging.error(
            "%s: %s\nHandling authentication error...",
            e.__class__.__name__,
            e,
        )
        
        # Only try to handle session files if NOT using in_memory mode
        if not common_params.get("in_memory") and os.path.exists("./my_account.session"):
            try:
                os.rename("./my_account.session", "./my_account.session-old")
                logging.warning("Moved session file to my_account.session-old")
            except (FileNotFoundError, OSError) as file_error:
                logging.warning("Could not move session file: %s", file_error)
        else:
            logging.warning("Using in-memory session, no file cleanup needed")

        if USING_DB_SESSION and PRIMARY_ACCOUNT_ID:
            try:
                AccountManager.clear_account_session(PRIMARY_ACCOUNT_ID, status="auth_error")
                logging.error(
                    "Cleared stored session for account ID %s due to authentication error.",
                    PRIMARY_ACCOUNT_ID,
                )
            except Exception as cleanup_error:
                logging.error("Failed to clear account session: %s", cleanup_error)
            logging.error(
                "Primary account session is no longer valid. Re-authenticate the account via the dashboard to restart the userbot."
            )
            lock_manager.release_lock()
            release_singleton_lock()
            raise SystemExit(1)

        lock_manager.release_lock()
        release_singleton_lock()
        restart()

    load_missing_modules()
    module_manager = ModuleManager.get_instance()
    info = db.get("core.updater", "restart_info")

    if info:
        try:
            await app.edit_message_text(
                info["chat_id"],
                info["message_id"],
                "<b>Loading modules...</b>",
            )
        except errors.RPCError as e:
            logging.debug(f"Failed to edit message during module loading: {e}")

    await module_manager.load_modules(app)

    if info:
        text = {
            "restart": "<b>Restart completed!</b>",
            "update": "<b>Update process completed!</b>",
        }[info["type"]]

        if module_manager.failed_modules > 0:
            failed_list = "\n".join(
                [f"• <code>{m}</code>" for m in module_manager.failed_list]
            )
            text += (
                f"\n\n[E] <b>Failed to load {module_manager.failed_modules} module(s):</b>\n"
                f"{failed_list}\n\n"
                "<i>Please check logs for more details.</i>"
            )
        try:
            await app.edit_message_text(info["chat_id"], info["message_id"], text)
        except errors.RPCError as e:
            logging.debug(f"Failed to edit message after restart: {e}")
        db.remove("core.updater", "restart_info")

    # required for sessionkiller module
    if db.get("core.sessionkiller", "enabled", False):
        db.set(
            "core.sessionkiller",
            "auths_hashes",
            [
                auth.hash
                for auth in (await app.invoke(GetAuthorizations())).authorizations
            ],
        )

    logging.info("Moon-Userbot started!")

    app.loop.create_task(rentry_cleanup_job())

    await idle()

    await app.stop()
    
    # Release distributed lock
    lock_manager.release_lock()
    release_singleton_lock()


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Received interrupt signal, shutting down gracefully...")
        release_singleton_lock()
    except Exception as e:
        logging.error("💥 Unhandled exception: %s", e)
        release_singleton_lock()
        raise
