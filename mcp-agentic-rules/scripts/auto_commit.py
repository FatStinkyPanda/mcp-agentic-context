#!/usr/bin/env python3
"""
MCP Auto-Commit System
Automatically creates frequent commits for backup/restore points during development.
"""

import os
import sys
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime, timedelta


class AutoCommitManager:
    """Manages automatic commits for backup and restore points."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.config_file = self.project_root / ".mcp" / "auto_commit_config.json"
        self.state_file = self.project_root / ".mcp" / "auto_commit_state.json"
        self.load_config()
        self.load_state()

    def load_config(self):
        """Load or create auto-commit configuration."""
        default_config = {
            "enabled": True,
            "min_interval_minutes": 15,  # Minimum time between auto-commits
            "max_changes_before_commit": 50,  # Max files changed before forcing commit
            "commit_message_prefix": "[AUTO-BACKUP]",
            "include_timestamp": True,
            "track_file_count": True,
            "branch_protection": ["main", "master", "production"],  # Don't auto-commit on these
        }

        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = {**default_config, **json.load(f)}
        else:
            self.config = default_config
            self.save_config()

    def save_config(self):
        """Save auto-commit configuration."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def load_state(self):
        """Load auto-commit state."""
        default_state = {
            "last_auto_commit": None,
            "total_auto_commits": 0,
            "files_changed_since_last": 0,
        }

        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                self.state = {**default_state, **json.load(f)}
        else:
            self.state = default_state
            self.save_state()

    def save_state(self):
        """Save auto-commit state."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_current_branch(self) -> str:
        """Get current git branch."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=5
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def is_protected_branch(self) -> bool:
        """Check if current branch is protected from auto-commits."""
        current_branch = self.get_current_branch()
        return current_branch in self.config.get("branch_protection", [])

    def get_git_status(self) -> dict:
        """Get current git status."""
        try:
            # Get modified files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=10
            )

            if result.returncode != 0:
                return {"has_changes": False, "files": [], "count": 0}

            lines = result.stdout.strip().split('\n')
            files = [line[3:] for line in lines if line.strip()]

            return {
                "has_changes": len(files) > 0,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            print(f"[AUTO-COMMIT] Error getting git status: {e}")
            return {"has_changes": False, "files": [], "count": 0}

    def should_auto_commit(self) -> tuple[bool, str]:
        """
        Determine if an auto-commit should be made.
        Returns: (should_commit, reason)
        """
        if not self.config.get("enabled", True):
            return False, "Auto-commit disabled in config"

        if self.is_protected_branch():
            return False, f"Protected branch: {self.get_current_branch()}"

        status = self.get_git_status()
        if not status["has_changes"]:
            return False, "No changes to commit"

        # Check if enough time has passed
        last_commit_time = self.state.get("last_auto_commit")
        min_interval = self.config.get("min_interval_minutes", 15)

        if last_commit_time:
            last_dt = datetime.fromisoformat(last_commit_time)
            elapsed = datetime.now() - last_dt

            if elapsed < timedelta(minutes=min_interval):
                remaining = timedelta(minutes=min_interval) - elapsed
                return False, f"Too soon (wait {remaining.total_seconds():.0f}s)"

        # Check if too many files changed (force commit)
        max_changes = self.config.get("max_changes_before_commit", 50)
        if status["count"] >= max_changes:
            return True, f"Too many changes ({status['count']} >= {max_changes})"

        # Normal auto-commit after interval
        return True, f"Time-based backup ({status['count']} files changed)"

    def create_auto_commit(self, force: bool = False) -> bool:
        """Create an automatic backup commit."""
        should_commit, reason = self.should_auto_commit()

        if not should_commit and not force:
            print(f"[AUTO-COMMIT] Skipped: {reason}")
            return False

        print(f"[AUTO-COMMIT] Creating backup: {reason}")

        status = self.get_git_status()
        if not status["has_changes"]:
            print("[AUTO-COMMIT] No changes to commit")
            return False

        # Create commit message
        prefix = self.config.get("commit_message_prefix", "[AUTO-BACKUP]")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        message_parts = [prefix]

        if self.config.get("include_timestamp", True):
            message_parts.append(timestamp)

        if self.config.get("track_file_count", True):
            message_parts.append(f"({status['count']} files)")

        commit_message = " ".join(message_parts)

        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.project_root,
                check=True,
                timeout=30
            )

            # Create commit
            subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=self.project_root,
                check=True,
                timeout=30
            )

            # Update state
            self.state["last_auto_commit"] = datetime.now().isoformat()
            self.state["total_auto_commits"] = self.state.get("total_auto_commits", 0) + 1
            self.state["files_changed_since_last"] = 0
            self.save_state()

            print(f"[AUTO-COMMIT] ✅ Backup created: {commit_message}")
            print(f"[AUTO-COMMIT] Total auto-backups: {self.state['total_auto_commits']}")

            return True

        except subprocess.CalledProcessError as e:
            print(f"[AUTO-COMMIT] ❌ Commit failed: {e}")
            return False
        except Exception as e:
            print(f"[AUTO-COMMIT] ❌ Unexpected error: {e}")
            return False

    def list_auto_commits(self, limit: int = 10) -> list:
        """List recent auto-commits."""
        try:
            prefix = self.config.get("commit_message_prefix", "[AUTO-BACKUP]")
            result = subprocess.run(
                ["git", "log", f"--grep=^{prefix}", f"-{limit}", "--oneline"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=10
            )

            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            return []
        except Exception:
            return []

    def get_restore_points(self) -> list:
        """Get list of restore points (auto-commits)."""
        commits = self.list_auto_commits(limit=50)
        restore_points = []

        for i, commit in enumerate(commits):
            if commit.strip():
                hash_msg = commit.split(' ', 1)
                if len(hash_msg) == 2:
                    restore_points.append({
                        "index": i,
                        "hash": hash_msg[0],
                        "message": hash_msg[1],
                    })

        return restore_points

    def restore_to_point(self, commit_hash: str, hard: bool = False) -> bool:
        """Restore to a specific restore point."""
        try:
            if hard:
                print(f"[AUTO-COMMIT] ⚠️ Hard reset to {commit_hash}")
                subprocess.run(
                    ["git", "reset", "--hard", commit_hash],
                    cwd=self.project_root,
                    check=True,
                    timeout=30
                )
            else:
                print(f"[AUTO-COMMIT] Soft reset to {commit_hash}")
                subprocess.run(
                    ["git", "reset", "--soft", commit_hash],
                    cwd=self.project_root,
                    check=True,
                    timeout=30
                )

            print(f"[AUTO-COMMIT] ✅ Restored to {commit_hash}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[AUTO-COMMIT] ❌ Restore failed: {e}")
            return False


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Auto-Commit Manager")
    parser.add_argument("command",
                       choices=["check", "commit", "list", "restore", "status", "enable", "disable"],
                       help="Command to execute")
    parser.add_argument("--force", action="store_true",
                       help="Force commit even if interval hasn't passed")
    parser.add_argument("--hash", type=str,
                       help="Commit hash for restore command")
    parser.add_argument("--hard", action="store_true",
                       help="Hard reset when restoring")
    parser.add_argument("--limit", type=int, default=10,
                       help="Limit for list command")

    args = parser.parse_args()

    manager = AutoCommitManager()

    if args.command == "check":
        should, reason = manager.should_auto_commit()
        print(f"Should auto-commit: {should}")
        print(f"Reason: {reason}")
        sys.exit(0 if should else 1)

    elif args.command == "commit":
        success = manager.create_auto_commit(force=args.force)
        sys.exit(0 if success else 1)

    elif args.command == "list":
        commits = manager.list_auto_commits(limit=args.limit)
        print(f"Recent auto-commits (last {args.limit}):")
        for commit in commits:
            if commit.strip():
                print(f"  {commit}")

    elif args.command == "restore":
        if not args.hash:
            print("Error: --hash required for restore command")
            sys.exit(1)
        success = manager.restore_to_point(args.hash, hard=args.hard)
        sys.exit(0 if success else 1)

    elif args.command == "status":
        print(f"Auto-commit enabled: {manager.config.get('enabled', True)}")
        print(f"Min interval: {manager.config.get('min_interval_minutes', 15)} minutes")
        print(f"Total auto-commits: {manager.state.get('total_auto_commits', 0)}")
        print(f"Last auto-commit: {manager.state.get('last_auto_commit', 'Never')}")
        print(f"Current branch: {manager.get_current_branch()}")

        status = manager.get_git_status()
        print(f"Files changed: {status['count']}")

        should, reason = manager.should_auto_commit()
        print(f"Should auto-commit: {should} ({reason})")

    elif args.command == "enable":
        manager.config["enabled"] = True
        manager.save_config()
        print("[AUTO-COMMIT] ✅ Auto-commit enabled")

    elif args.command == "disable":
        manager.config["enabled"] = False
        manager.save_config()
        print("[AUTO-COMMIT] ❌ Auto-commit disabled")


if __name__ == "__main__":
    main()
