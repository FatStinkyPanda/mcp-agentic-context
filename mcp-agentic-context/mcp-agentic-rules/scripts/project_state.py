"""
Project State Manager
=====================
Manage the project state file - the anchor for autonomous AI agents.

Based on active_context_compression.md 3-tier architecture:
- State file acts as "Save Game" for AI agents
- Contains goals, milestones, current task, bugs, lessons learned
- Updated after each agent cycle

Usage:
    python mcp.py state                  # View current state
    python mcp.py state --set-goal "..."  # Set global goal
    python mcp.py state --add-task "..."  # Add task to queue
    python mcp.py state --learn "..."     # Add lesson learned
"""

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from .utils import (
    find_project_root,
    get_project_boundary,
    Console
)


@dataclass
class ProjectState:
    """The project state - anchor for autonomous agents."""
    
    # High-level goal
    global_goal: str = ""
    
    # Progress tracking
    completed_milestones: List[str] = field(default_factory=list)
    current_active_task: str = ""
    next_step_queue: List[str] = field(default_factory=list)
    
    # Issues
    known_bugs: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    
    # Learning
    lessons_learned: List[str] = field(default_factory=list)
    patterns_discovered: List[str] = field(default_factory=list)
    
    # Metadata
    last_updated: str = ""
    version: int = 1
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProjectState':
        """Create from dictionary."""
        # Handle missing fields gracefully
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)
    
    def update_timestamp(self):
        """Update the last_updated timestamp."""
        self.last_updated = datetime.utcnow().isoformat() + 'Z'


def get_state_path(root: Path = None) -> Path:
    """Get path to project state file."""
    if root is None:
        root = get_project_boundary() or find_project_root() or Path.cwd()
    return root / '.mcp' / 'project_state.json'


def load_state(root: Path = None) -> ProjectState:
    """Load project state from disk."""
    state_path = get_state_path(root)
    
    if state_path.exists():
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ProjectState.from_dict(data)
        except Exception as e:
            Console.warn(f"Could not load state: {e}")
    
    return ProjectState()


def save_state(state: ProjectState, root: Path = None):
    """Save project state to disk."""
    state_path = get_state_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    
    state.update_timestamp()
    
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state.to_dict(), f, indent=2)
    
    Console.ok(f"State saved to {state_path}")


def format_state(state: ProjectState) -> str:
    """Format state as readable markdown."""
    lines = [
        "# Project State",
        "",
        f"**Last Updated:** {state.last_updated or 'Never'}",
        "",
    ]
    
    if state.global_goal:
        lines.extend([
            "## Global Goal",
            f"> {state.global_goal}",
            "",
        ])
    
    if state.current_active_task:
        lines.extend([
            "## Current Task",
            f"**Active:** {state.current_active_task}",
            "",
        ])
    
    if state.next_step_queue:
        lines.extend([
            "## Next Steps",
        ])
        for i, step in enumerate(state.next_step_queue[:10], 1):
            lines.append(f"{i}. {step}")
        if len(state.next_step_queue) > 10:
            lines.append(f"... and {len(state.next_step_queue) - 10} more")
        lines.append("")
    
    if state.completed_milestones:
        lines.extend([
            "## Completed Milestones",
        ])
        for milestone in state.completed_milestones[-10:]:
            lines.append(f"- [x] {milestone}")
        lines.append("")
    
    if state.known_bugs:
        lines.extend([
            "## Known Bugs",
        ])
        for bug in state.known_bugs:
            lines.append(f"- {bug}")
        lines.append("")
    
    if state.lessons_learned:
        lines.extend([
            "## Lessons Learned",
            "",
            "*These are injected into AI agent context:*",
            "",
        ])
        for lesson in state.lessons_learned:
            lines.append(f"- {lesson}")
        lines.append("")
    
    return '\n'.join(lines)


def get_warm_context(state: ProjectState, max_tokens: int = 500) -> str:
    """
    Get state as warm context for AI agents.
    
    This is the "Tier 2" context that should be injected into
    every agent's context window.
    """
    lines = [
        "# Project Context (Warm)",
        "",
    ]
    
    if state.global_goal:
        lines.append(f"**Goal:** {state.global_goal}")
    
    if state.current_active_task:
        lines.append(f"**Current Task:** {state.current_active_task}")
    
    if state.next_step_queue:
        lines.append(f"**Next:** {state.next_step_queue[0] if state.next_step_queue else 'None'}")
    
    lines.append("")
    
    # Lessons learned are critical - always include
    if state.lessons_learned:
        lines.append("**Remember:**")
        for lesson in state.lessons_learned[-10:]:  # Last 10 lessons
            lines.append(f"- {lesson}")
    
    # Truncate if needed
    result = '\n'.join(lines)
    max_chars = max_tokens * 4
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (truncated)"
    
    return result


def main():
    """CLI entry point."""
    Console.header("Project State Manager")
    
    root = get_project_boundary() or find_project_root() or Path.cwd()
    state = load_state(root)
    
    # Handle commands
    args = sys.argv[1:]
    
    # Set global goal
    for i, arg in enumerate(args):
        if arg == '--set-goal' and i + 1 < len(args):
            state.global_goal = args[i + 1]
            save_state(state, root)
            Console.ok(f"Set goal: {state.global_goal}")
            return 0
    
    # Set current task
    for i, arg in enumerate(args):
        if arg == '--set-task' and i + 1 < len(args):
            state.current_active_task = args[i + 1]
            save_state(state, root)
            Console.ok(f"Set task: {state.current_active_task}")
            return 0
    
    # Add to next steps queue
    for i, arg in enumerate(args):
        if arg == '--add-task' and i + 1 < len(args):
            state.next_step_queue.append(args[i + 1])
            save_state(state, root)
            Console.ok(f"Added task: {args[i + 1]}")
            return 0
    
    # Complete current task
    if '--complete' in args:
        if state.current_active_task:
            state.completed_milestones.append(state.current_active_task)
            Console.ok(f"Completed: {state.current_active_task}")
            
            # Move next task to current
            if state.next_step_queue:
                state.current_active_task = state.next_step_queue.pop(0)
                Console.info(f"New task: {state.current_active_task}")
            else:
                state.current_active_task = ""
            
            save_state(state, root)
        else:
            Console.warn("No current task to complete")
        return 0
    
    # Add lesson learned
    for i, arg in enumerate(args):
        if arg in ('--learn', '--lesson') and i + 1 < len(args):
            lesson = args[i + 1]
            if lesson not in state.lessons_learned:
                state.lessons_learned.append(lesson)
                save_state(state, root)
                Console.ok(f"Learned: {lesson}")
            else:
                Console.warn("Lesson already recorded")
            return 0
    
    # Add known bug
    for i, arg in enumerate(args):
        if arg == '--bug' and i + 1 < len(args):
            state.known_bugs.append(args[i + 1])
            save_state(state, root)
            Console.ok(f"Bug recorded: {args[i + 1]}")
            return 0
    
    # Show warm context (for AI)
    if '--warm' in args or '--context' in args:
        print(get_warm_context(state))
        return 0
    
    # Show JSON
    if '--json' in args:
        print(json.dumps(state.to_dict(), indent=2))
        return 0
    
    # Default: show formatted state
    print(format_state(state))
    
    if not state.global_goal and not state.current_active_task:
        Console.info("\nTip: Set a goal with --set-goal \"Your goal here\"")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
