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
import re
import sys
import shutil
import subprocess

from pyrogram import Client, filters
from pyrogram.types import Message

from utils.misc import modules_help, prefix, requirements_list
from utils.db import db
from utils.scripts import format_exc, restart


def check_command(command):
    return shutil.which(command) is not None


def validate_package_name(package: str) -> bool:
    """
    Validate package name against PEP 508 naming conventions.
    Returns True if package name is safe to use with pip.
    """
    if not package or not isinstance(package, str):
        return False
    package_pattern = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$')
    return bool(package_pattern.match(package)) and len(package) <= 214


@Client.on_message(filters.command("restart", prefix) & filters.me)
async def restart_cmd(_, message: Message):
    db.set(
        "core.updater",
        "restart_info",
        {
            "type": "restart",
            "chat_id": message.chat.id,
            "message_id": message.id,
        },
    )

    if "LAVHOST" in os.environ:
        await message.edit("<b>Your lavHost is restarting...</b>")
        os.system("lavhost restart")
        return

    await message.edit("<b>Restarting...</b>")
    if os.path.exists("moonlogs.txt"):
        os.remove("moonlogs.txt")
    restart()


@Client.on_message(filters.command("update", prefix) & filters.me)
async def update(_, message: Message):
    db.set(
        "core.updater",
        "restart_info",
        {
            "type": "update",
            "chat_id": message.chat.id,
            "message_id": message.id,
        },
    )

    if "LAVHOST" in os.environ:
        await message.edit("<b>Your lavHost is updating...</b>")
        os.system("lavhost update")
        return

    await message.edit("<b>Updating...</b>")
    try:
        if not check_command("termux-setup-storage"):
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "pip"], check=True
            )
        subprocess.run(["git", "pull"], check=True)

        if (
            os.path.exists("requirements.txt")
            and os.path.getsize("requirements.txt") > 0
        ):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-U",
                    "-r",
                    "requirements.txt",
                ],
                check=True,
            )

        if requirements_list:
            validated_packages = [pkg for pkg in requirements_list if validate_package_name(pkg)]
            if validated_packages:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", *validated_packages],
                    check=True,
                )
    except Exception as e:
        await message.edit(format_exc(e))
        db.remove("core.updater", "restart_info")
    else:
        await message.edit("<b>Updating: done! Restarting...</b>")
        if os.path.exists("moonlogs.txt"):
            os.remove("moonlogs.txt")
        restart()


modules_help["updater"] = {
    "update": "Update the userbot. If new core modules are avaliable, they will be installed",
    "restart": "Restart userbot",
}
