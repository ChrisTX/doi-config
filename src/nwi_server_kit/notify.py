"""The admins' notifications: of versions that used up their tries (health.py) and of servers that
failed for good (nwi-notify-failure@.service, OnFailure= of nwi-server@.service).

A notification is printed to the journal and queued in /run/nwi-server/notify, or the queue of
NWI_NOTIFY_DIR, e.g. the update's, which runs as a user of its own (/run/nwi-server/notify-update);
nwi-notify.path watches them: nwi-notify.service sends it by mail through sendmail(8), to root, whose mail the system's
aliases forward, and to the addresses of NOTIFY_MAIL (space-separated), and to Discord with the webhook
of the credential nwi-server.discord-webhook, if there's one. NOTIFY_MAIL is set in
/etc/nwi-server/notify.env.

The commands: cli/notify.py.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from .games import read_env

QUEUE = Path("/run/nwi-server/notify")
# The update's queue, which it writes as its own user (nwi-update.service's RuntimeDirectory=)
UPDATE_QUEUE = Path("/run/nwi-server/notify-update")


def own_queue() -> Path:
    """The queue a notification of this process goes into."""
    return (
        Path(os.environ["NWI_NOTIFY_DIR"])
        if os.environ.get("NWI_NOTIFY_DIR")
        else QUEUE
    )


SETTINGS = Path("/etc/nwi-server/notify.env")
# Discord takes at most 2000 characters a message
DISCORD_LIMIT = 2000


def queue(subject: str, body: str) -> None:
    """Print a notification to the journal and queue it for the admins."""
    print(f"{subject}\n{body}", file=sys.stderr)
    queue_dir = own_queue()
    queue_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{os.getpid()}.json"
    temporary = queue_dir / f".{name}"
    temporary.write_text(json.dumps({"subject": subject, "body": body}))
    temporary.rename(queue_dir / name)


def send_mail(subject: str, body: str, recipients: list[str]) -> None:
    message = EmailMessage()
    message["Subject"] = f"[nwi-server] {subject}"
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    subprocess.run(
        ["sendmail", "-oi", "-t"], input=message.as_bytes(), check=True, timeout=60
    )


def send_discord(subject: str, body: str, webhook: str) -> None:
    content = f"**{subject}**\n{body}"
    if len(content) > DISCORD_LIMIT:
        content = content[: DISCORD_LIMIT - 1] + "…"
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"content": content}).encode(),
        # Discord refuses Python's own user agent
        headers={"Content-Type": "application/json", "User-Agent": "nwi-server-kit"},
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def send() -> int:
    """Send the queued notifications and remove them; 1 if one couldn't be sent."""
    settings = read_env(SETTINGS) if SETTINGS.is_file() else {}
    recipients = ["root", *settings.get("NOTIFY_MAIL", "").split()]
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    webhook_file = (
        Path(credentials) / "nwi-server.discord-webhook" if credentials else None
    )
    webhook = (
        webhook_file.read_text().strip()
        if webhook_file is not None and webhook_file.is_file()
        else None
    )
    mail = shutil.which("sendmail") is not None
    if not mail:
        print("No sendmail, no mail is sent", file=sys.stderr)
    status = 0
    queued = [
        path
        for queue_dir in (QUEUE, UPDATE_QUEUE)
        if queue_dir.is_dir()
        for path in queue_dir.glob("*.json")
    ]
    # In the order they were queued: their names start with the time
    for path in sorted(queued, key=lambda path: path.name):
        message = json.loads(path.read_text())
        sent = False
        if mail:
            try:
                send_mail(message["subject"], message["body"], recipients)
                sent = True
            except (OSError, subprocess.SubprocessError) as error:
                print(f"The mail of {path.name} failed: {error}", file=sys.stderr)
        if webhook:
            try:
                send_discord(message["subject"], message["body"], webhook)
                sent = True
            except OSError as error:
                print(
                    f"Discord's message of {path.name} failed: {error}", file=sys.stderr
                )
        # Removed even if it couldn't be sent: the journal has it, and a queue that isn't empty would
        # start nwi-notify.service again at once
        path.unlink()
        if not sent and (mail or webhook):
            status = 1
    return status


def failed(unit: str) -> None:
    """Queue a notification of a unit that failed, with the end of its journal."""
    journal = subprocess.run(
        [
            "journalctl",
            "--unit",
            unit,
            "--lines",
            "20",
            "--no-pager",
            "--output",
            "cat",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    queue(f"{unit} failed", f"{unit} failed and isn't restarted any more.\n\n{journal}")
