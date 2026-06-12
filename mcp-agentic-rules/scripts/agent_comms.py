#!/usr/bin/env python3
"""
MCP Agent Collaboration Layer (ACL)
Enables secure, bidirectional communication and presence tracking between AI agents.
"""

from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time

def get_nsync_path() -> Path:
    """
    Root directory shared with NSync for cross-machine agent communication.

    Configure with the MCP_NSYNC_PATH environment variable; defaults to the
    per-user MCP data directory so no machine-specific path is baked into
    the source.
    """
    override = os.environ.get('MCP_NSYNC_PATH')
    if override:
        return Path(override)
    return Path.home() / '.mcp' / 'nsync'

def get_comms_dir() -> Path:
    comms_dir = get_nsync_path() / ".nsync_agents"
    if not comms_dir.exists():
        comms_dir.mkdir(parents=True, exist_ok=True)
    return comms_dir

def get_mailbox_dir() -> Path:
    mailbox = get_comms_dir() / "messages"
    if not mailbox.exists():
        mailbox.mkdir(parents=True, exist_ok=True)
    return mailbox

def get_telegram_inbox_dir() -> Path:
    inbox = get_comms_dir() / "telegram_inbox"
    if not inbox.exists():
        inbox.mkdir(parents=True, exist_ok=True)
    return inbox

def find_seat_file(start=None):
    """Walk upward from start (default cwd) looking for .mcp/seat.json — the
    per-workdir identity binding. Stops at the repo root (.git) or 10 parents.
    The ONE seat-file locator; agent_collab's seat verbs use this too."""
    cur = Path(start or Path.cwd()).resolve()
    for _ in range(10):
        p = cur / ".mcp" / "seat.json"
        if p.is_file():
            return p
        if (cur / ".git").exists() or cur.parent == cur:
            return None
        cur = cur.parent
    return None


_seat_cache = {}


def clear_seat_cache():
    _seat_cache.clear()


def get_hostname():
    """Identity resolution: AGENT_IDENTITY env > workdir seat file > hostname.
    The seat file is what lets MANY agents share one machine: each worktree
    binds its own call-sign, so the hostname fallback (which would merge every
    session on the device into one identity) only applies to unseated dirs."""
    identity = os.environ.get("AGENT_IDENTITY")
    if identity:
        return identity
    key = str(Path.cwd())
    if key not in _seat_cache:
        ident = None
        seat = find_seat_file()
        if seat:
            try:
                ident = json.loads(seat.read_text(encoding="utf-8")).get("identity")
            except Exception:
                ident = None
        _seat_cache[key] = ident
    return _seat_cache[key] or socket.gethostname()


def _collab():
    """Lazy import (agent_collab imports this module at load time)."""
    try:
        from scripts import agent_collab
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        sys.modules.pop("scripts", None)   # purge a cached foreign 'scripts' pkg
        from scripts import agent_collab
    return agent_collab


def _nsync_kick(min_interval: float = 15.0):
    """Debounced, timeout-bounded NSync trigger. 100 agents heartbeating must
    not each spawn an unbounded subprocess; honors MCP_NSYNC_AUTOSYNC=0."""
    if os.environ.get("MCP_NSYNC_AUTOSYNC") == "0":
        return
    marker = get_comms_dir() / ".last_sync"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < min_interval:
            return
        marker.touch()
    except OSError:
        pass
    try:
        mcp_py = Path(__file__).parents[1] / "mcp.py"
        subprocess.run([sys.executable, str(mcp_py), "nsync", "sync"],
                       capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        pass


class AgentPresence:
    """Manages local agent presence and heartbeats."""
    @staticmethod
    def update(status="active", task="monitoring"):
        # ONE presence writer: agent_collab.heartbeat (atomic write, workdir +
        # session stamped, collision detection). This wrapper only adds the
        # debounced NSync propagation.
        data, _ = _collab().heartbeat(get_hostname(), status, task)
        _nsync_kick()
        return data

    @staticmethod
    def get_remote_status():
        comms_dir = get_comms_dir()
        remote_status = {}
        for f in comms_dir.glob("*.json"):
            if f.stem != get_hostname():
                try:
                    with open(f, "r") as pf:
                        remote_status[f.stem] = json.load(pf)
                except Exception:
                    pass
        return remote_status

def send_message(recipient: str, msg_type: str, content: dict, sender: str = None):
    """Deliver a message into the recipient's OWN directory with a
    maildir-unique name (time_ns + pid + random): two same-millisecond sends
    can never overwrite each other, and recipient names can never prefix-match
    another agent's mail (the legacy flat `a_b_id.json` layout let agent 'a'
    steal mail addressed to 'a_b')."""
    sender = sender or get_hostname()
    rdir = get_mailbox_dir() / recipient
    rdir.mkdir(parents=True, exist_ok=True)
    msg_file = rdir / ("%s.%d.%d.%s.json"
                       % (sender, time.time_ns(), os.getpid(), os.urandom(2).hex()))
    payload = {
        "id": time.time_ns() // 1_000_000,
        "from": sender,
        "to": recipient,
        "type": msg_type,
        "content": content,
        "timestamp": time.time(),
        "v": 2,
    }
    with open(msg_file, "x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[COMMS] Message sent to {recipient}: {msg_type}")
    _nsync_kick()
    return msg_file


def listen_for_messages(identity: str = None):
    """Poll + consume this agent's mail. Consumption is CLAIM-BY-RENAME:
    exactly one concurrent consumer wins each message (rename is the CAS),
    so two processes in one seat can poll without double-processing.
    Reads both the v2 per-recipient directory and the legacy flat layout."""
    me = identity or get_hostname()
    mailbox = get_mailbox_dir()
    messages = []
    candidates = []
    mydir = mailbox / me
    if mydir.is_dir():
        candidates += sorted(mydir.glob("*.json"))
    candidates += sorted(mailbox.glob(f"{me}_*.json"))     # legacy flat layout
    for f in candidates:
        # The claim destination MUST be unique per claimer: empirically on
        # Windows two concurrent renames of one src to the SAME dst can both
        # report success — deterministic destinations are not a CAS there.
        claimed = f.with_name("%s.claimed.%d.%s"
                              % (f.name, os.getpid(), os.urandom(3).hex()))
        try:
            os.replace(f, claimed)
        except (FileNotFoundError, PermissionError, OSError):
            continue            # another consumer won, or a transient Windows lock
        try:
            msg = json.loads(claimed.read_text(encoding="utf-8"))
        except Exception:
            try:
                claimed.unlink()
            except OSError:
                pass
            continue
        if f.parent == mailbox and msg.get("to") not in (None, me):
            # legacy prefix-glob caught someone else's mail — restore untouched
            try:
                os.replace(claimed, f)
            except OSError:
                pass
            continue
        messages.append(msg)
        try:
            claimed.unlink()
        except OSError:
            pass
    return messages

def _claim_file(f: Path):
    """Claim-by-rename consumption: exactly one concurrent consumer gets the
    message. The destination embeds pid+random because deterministic rename
    destinations are NOT a CAS on Windows (two renames can both 'succeed').
    Returns the parsed payload or None."""
    claimed = f.with_name("%s.claimed.%d.%s"
                          % (f.name, os.getpid(), os.urandom(3).hex()))
    try:
        os.replace(f, claimed)
    except (FileNotFoundError, PermissionError, OSError):
        return None
    try:
        msg = json.loads(claimed.read_text(encoding="utf-8"))
    except Exception:
        msg = None
    try:
        claimed.unlink()
    except OSError:
        pass
    return msg


def listen_for_telegram_messages():
    """Polls for Telegram messages. Background agents wait for Antigravity priority."""
    inbox = get_telegram_inbox_dir()
    hostname = get_hostname()
    agent_identity = os.getenv("AGENT_IDENTITY", hostname)  # Use AGENT_IDENTITY if set, else hostname

    messages = []

    # Priority 1: Messages directly for me (based on AGENT_IDENTITY)
    for f in inbox.glob(f"{agent_identity}_*.json"):
        msg = _claim_file(f)
        if msg:
            messages.append(msg)

    # Skip fallback logic if I AM Antigravity (I already checked)
    if agent_identity.lower() == "antigravity":
        return messages

    # Priority 2: Fallback for Antigravity (Background Agents only)
    # Background agents (Quasar/wizardpanda) only take Antigravity messages if stale
    for f in inbox.glob("Antigravity_*.json"):
        try:
            age = time.time() - f.stat().st_mtime
        except OSError:
            continue
        # If the IDE brain hasn't taken it in 60s, a background agent can help
        if age > 60:
            # The claim-by-rename IS the double-response arbiter; the primary
            # ordering below only decides who tries first.
            is_primary = False
            if hostname.lower() == "quasar":
                is_primary = True
            else:
                remotes = AgentPresence.get_remote_status()
                quasar_active = False
                for h, d in remotes.items():
                    if h.lower() == "quasar" and time.time() - d.get('timestamp', 0) < 120:
                        quasar_active = True
                if not quasar_active:
                    is_primary = True
            if is_primary:
                msg = _claim_file(f)
                if msg:
                    messages.append(msg)
                    print(f"[COMMS] Handled Antigravity fallback message (Age: {int(age)}s)")

    return messages

def notify_user_telegram(text: str):
    """Sends a notification back to the user via the Telegram Bridge."""
    # The bridge will watch this directory for outgoing alerts
    outbox = get_comms_dir() / "telegram_outbox"
    if not outbox.exists():
        outbox.mkdir(parents=True, exist_ok=True)

    msg_file = outbox / ("out_%d_%d_%s.json"
                         % (time.time_ns(), os.getpid(), os.urandom(2).hex()))
    with open(msg_file, "x", encoding="utf-8") as f:
        json.dump({"text": text, "from": get_hostname(), "timestamp": time.time()}, f, indent=2)
    print(f"[COMMS] Notification queued for Telegram: {text[:50]}...")

def show_status():
    """Displays local and remote agent status."""
    hostname = get_hostname()
    presence_file = get_comms_dir() / f"{hostname}.json"
    local = {}
    if presence_file.exists():
        with open(presence_file, "r") as f:
            local = json.load(f)
    else:
        local = AgentPresence.update() # Create if missing

    print("--- Local Agent Priority ---")
    print(f"Host:   {local.get('hostname', hostname)}")
    print(f"Status: {local.get('status', 'unknown')}")
    print(f"Task:   {local.get('current_task', 'unknown')}")
    print(f"Sync:   {local.get('last_seen', 'unknown')}")

    print("\n--- Remote Agents ---")
    remotes = AgentPresence.get_remote_status()
    if not remotes:
        print("No remote agents detected yet.")
    fresh = _collab().PRESENCE_FRESH_SECONDS
    for host, data in remotes.items():
        age = time.time() - data['timestamp']
        active_str = "[ACTIVE]" if age < fresh else "[OFFLINE/STALE]"
        print(f"Host:   {host} {active_str}")
        print(f"Status: {data['status']}")
        print(f"Task:   {data['current_task']}")
        print(f"Last heartbeat: {int(age)}s ago")
        print("-" * 20)

def show_help():
    print("MCP Agent Collaboration Layer (ACL)")
    print("Usage: mcp comms <command> [args]")
    print("\nCommands:")
    print("  status                Check local and remote agent presence")
    print("  send <host> <type> <msg> Send a message to a specific agent")
    print("  listen                Poll and display unread messages")
    print("  ping <host>           Quick verification of remote agent life")
    print("  heartbeat <status> <task> Update local presence info")
    print("  collaborate           Enter autonomous agent-to-agent team mode")

def handle_telegram_instruction(text):
    """Parses telegram text and tries to execute as an MCP command or route to Antigravity."""
    print(f"[EXEC] Parsing Telegram Task: {text}")

    # Check if this is the "Antigravity" agent (IDE session)
    # If so, send to Antigravity automation instead of running MCP commands
    hostname = get_hostname().lower()
    agent_identity = os.getenv("AGENT_IDENTITY", "").lower()

    # Route to Antigravity IDE automation if AGENT_IDENTITY is set to "Antigravity"
    if agent_identity == "antigravity":
        try:
            # Import antigravity automation module
            antigravity_path = Path(__file__).resolve().parent / "antigravity_automation.py"
            if antigravity_path.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location("antigravity_automation", antigravity_path)
                ag_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ag_module)

                # Send message to Antigravity IDE
                print("[INFO] Routing message to Antigravity IDE automation")
                response = ag_module.handle_antigravity_message(text)
                return response if response else "[ERROR] No response from Antigravity"
            else:
                print(f"[WARNING] antigravity_automation.py not found at {antigravity_path}")
                return "Antigravity automation module not found. Install with: python antigravity_automation.py install"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[ERROR] Antigravity automation failed: {e}\n{error_details}")
            return f"Error routing to Antigravity: {e}"

    # Otherwise, handle as regular MCP command
    mcp_py = Path(__file__).parents[1] / "mcp.py"

    # Simple mapping or direct attempt
    cmd_parts = text.split()
    if not cmd_parts: return "Empty command"

    # If the user says "status", run "mcp comms status"
    # If they say "scan", we might need more logic, but for now let's try direct mapping
    try:
        if text.lower() == "status":
            res = subprocess.run([sys.executable, str(mcp_py), "comms", "status"], capture_output=True, text=True)
            return res.stdout
        elif text.lower().startswith("run "):
            # e.g. "run script.py" -> "mcp nsync run script.py"
            script = text[4:].strip()
            res = subprocess.run([sys.executable, str(mcp_py), "nsync", "run", script], capture_output=True, text=True)
            return res.stdout
        else:
            # Try running it as a generic mcp command if it looks like one
            # Otherwise, just acknowledge.
            return f"Received: {text}. (Smart execution for this command pending development)"
    except Exception as e:
        return f"Error executing task: {e}"

def autonomous_loop():
    """Autonomous execution loop for AI agents."""
    hostname = get_hostname()
    print(f"[AUTONOMOUS] Agent {hostname} entered collaboration mode.")
    AgentPresence.update("active", "autonomous collaboration")

    try:
        while True:
            msgs = listen_for_messages()
            for m in msgs:
                print(f"\n[RECEIVED] From: {m['from']} | Type: {m['type']}")
                if m['type'] == "task" or m['type'] == "instruction":
                    task_text = m['content'].get('text', '')
                    result = handle_telegram_instruction(task_text)
                    send_message(m['from'], "result", {"text": result})

            # Check for Telegram instructions
            t_msgs = listen_for_telegram_messages()
            for tm in t_msgs:
                print(f"\n[TELEGRAM] Instruction received: {tm['text']}")
                result = handle_telegram_instruction(tm['text'])
                notify_user_telegram(f"Result for '{tm['text']}':\n{result}")

            time.sleep(5)
            # Periodic heartbeat
            AgentPresence.update("active", "listening for team tasks")
    except KeyboardInterrupt:
        print("\n[AUTONOMOUS] Collaboration mode stopped.")

def main():
    if len(sys.argv) < 2:
        show_help()
        return 0

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "status":
        show_status()
    elif cmd == "send" and len(args) >= 3:
        send_message(args[0], args[1], {"text": " ".join(args[2:])})
    elif cmd == "listen":
        msgs = listen_for_messages()
        if not msgs:
            print("No new messages.")
        for m in msgs:
            print(f"\n[FROM: {m['from']}] [TYPE: {m['type']}]")
            print(f"Content: {m['content']}")
    elif cmd == "ping" and args:
        remotes = AgentPresence.get_remote_status()
        if args[0] in remotes:
            age = time.time() - remotes[args[0]]['timestamp']
            if age < _collab().PRESENCE_FRESH_SECONDS:
                print(f"[OK] {args[0]} is ALIVE (Age: {int(age)}s)")
                return 0
        print(f"[FAIL] {args[0]} is UNREACHABLE or STALE")
        return 1
    elif cmd == "heartbeat" and len(args) >= 2:
        AgentPresence.update(args[0], args[1])
        print("[OK] Heartbeat updated.")
    elif cmd == "collaborate":
        autonomous_loop()
    else:
        show_help()
    return 0

if __name__ == "__main__":
    sys.exit(main())
