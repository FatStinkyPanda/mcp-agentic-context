"""
Project State
=============
Persistent goal, tasks, and notes for the current project, stored in
.mcp/project_state.json so every agent session shares the same picture.

Usage:
    python mcp.py state                      View current state
    python mcp.py state --set-goal "..."     Set the active goal
    python mcp.py state --add-task "..."     Append a task
    python mcp.py state --done N             Mark task N (1-based) complete
    python mcp.py state --note "..."         Record a note or lesson
"""

from datetime import datetime
from pathlib import Path
import json
import sys

from .utils import Console, find_project_root


def state_path(root: Path) -> Path:
    return Path(root) / ".mcp" / "project_state.json"


def load_state(root: Path) -> dict:
    path = state_path(root)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("goal", "")
                data.setdefault("tasks", [])
                data.setdefault("notes", [])
                return data
        except Exception as e:
            Console.warn(f"Could not read project state: {e}")
    return {"goal": "", "tasks": [], "notes": [], "updated": ""}


def save_state(state: dict, root: Path):
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def render(state: dict) -> str:
    lines = []
    lines.append("Goal: " + (state.get("goal") or "(not set)"))
    tasks = state.get("tasks", [])
    if tasks:
        lines.append("Tasks:")
        for i, task in enumerate(tasks, start=1):
            mark = "x" if task.get("done") else " "
            lines.append(f"  [{mark}] {i}. {task.get('text', '')}")
    else:
        lines.append("Tasks: (none)")
    notes = state.get("notes", [])
    if notes:
        lines.append("Notes:")
        for note in notes[-10:]:
            lines.append(f"  - {note}")
    if state.get("updated"):
        lines.append(f"Updated: {state['updated']}")
    return "\n".join(lines)


def main():
    """CLI entry point."""
    Console.header("Project State")

    argv = list(sys.argv[1:])
    root = find_project_root() or Path.cwd()
    state = load_state(root)

    def take_value(flag):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                value = argv[i + 1]
                del argv[i:i + 2]
                return value
            del argv[i]
        return None

    changed = False

    goal = take_value("--set-goal")
    if goal is not None:
        state["goal"] = goal
        changed = True
        Console.ok(f"Goal set: {goal}")

    task_text = take_value("--add-task")
    if task_text is not None:
        state["tasks"].append({
            "text": task_text,
            "done": False,
            "created": datetime.utcnow().isoformat() + "Z",
        })
        changed = True
        Console.ok(f"Task added ({len(state['tasks'])}): {task_text}")

    done_raw = take_value("--done")
    if done_raw is not None:
        try:
            idx = int(done_raw) - 1
            state["tasks"][idx]["done"] = True
            changed = True
            Console.ok(f"Task {idx + 1} done: {state['tasks'][idx]['text']}")
        except (ValueError, IndexError):
            Console.fail(f"No such task: {done_raw}")
            return 1

    note = take_value("--note")
    if note is not None:
        state["notes"].append(note)
        changed = True
        Console.ok("Note recorded")

    if changed:
        save_state(state, root)

    print()
    print(render(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
