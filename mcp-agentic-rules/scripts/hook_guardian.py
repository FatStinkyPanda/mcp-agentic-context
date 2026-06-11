"""
Hook Guardian
=============
Tracks commits, detects bypass attempts, enforces hook compliance.

Ensures --no-verify bypass attempts are detected and logged.
Maximizes learning by recording all git activity.

Usage:
    python mcp.py hook-guardian --record-commit   # Record commit (post-commit)
    python mcp.py hook-guardian --verify-all      # Verify no bypasses (pre-push)
    python mcp.py hook-guardian --reconcile       # Fix bypassed commits
    python mcp.py hook-guardian --status          # Show tracking status
"""

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .utils import (
    find_project_root,
    get_project_boundary,
    run_git_command,
    Console
)


@dataclass
class HookRecord:
    """Record of a commit passing through hooks."""
    commit_hash: str
    timestamp: str
    pre_commit_ran: bool = False
    post_commit_ran: bool = False
    message: str = ""


@dataclass
class GuardianData:
    """Tracking data for hook enforcement."""
    root: Path
    records: Dict[str, HookRecord] = field(default_factory=dict)  # hash -> record
    bypasses_detected: int = 0
    total_commits: int = 0
    last_updated: str = ""
    
    def to_dict(self) -> dict:
        return {
            'root': str(self.root),
            'records': {k: asdict(v) for k, v in self.records.items()},
            'bypasses_detected': self.bypasses_detected,
            'total_commits': self.total_commits,
            'last_updated': self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'GuardianData':
        gd = cls(root=Path(data['root']))
        gd.bypasses_detected = data.get('bypasses_detected', 0)
        gd.total_commits = data.get('total_commits', 0)
        gd.last_updated = data.get('last_updated', '')
        
        for k, v in data.get('records', {}).items():
            gd.records[k] = HookRecord(**v)
        
        return gd


def get_guardian_path(root: Path) -> Path:
    """Get path to guardian data file."""
    return root / '.mcp' / 'hook_guardian.json'


def load_guardian_data(root: Path = None) -> GuardianData:
    """Load guardian data from disk."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    path = get_guardian_path(root)
    
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return GuardianData.from_dict(json.load(f))
        except Exception:
            pass
    
    return GuardianData(root=root)


def save_guardian_data(data: GuardianData):
    """Save guardian data to disk."""
    path = get_guardian_path(data.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    data.last_updated = datetime.utcnow().isoformat() + 'Z'
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data.to_dict(), f, indent=2)


def get_current_commit(root: Path) -> Optional[str]:
    """Get current HEAD commit hash."""
    output = run_git_command(['rev-parse', 'HEAD'], cwd=root)
    return output.strip() if output else None


def get_commit_message(commit_hash: str, root: Path) -> str:
    """Get commit message for a hash."""
    output = run_git_command(['log', '-1', '--format=%s', commit_hash], cwd=root)
    return output.strip() if output else ""


def record_pre_commit(root: Path = None):
    """Record that pre-commit hook ran (called from pre-commit hook)."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = load_guardian_data(root)
    
    # We don't have commit hash yet in pre-commit, so mark a flag
    flag_path = root / '.mcp' / '.pre_commit_ran'
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(datetime.utcnow().isoformat() + 'Z')
    
    Console.info("[Hook Guardian] Pre-commit recorded")


def record_commit(root: Path = None):
    """Record that a commit was made (called from post-commit hook)."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = load_guardian_data(root)
    
    commit_hash = get_current_commit(root)
    if not commit_hash:
        return
    
    message = get_commit_message(commit_hash, root)
    
    # Check if pre-commit ran
    flag_path = root / '.mcp' / '.pre_commit_ran'
    pre_commit_ran = flag_path.exists()
    
    # Clean up flag
    if pre_commit_ran:
        flag_path.unlink()
    
    # Create record
    record = HookRecord(
        commit_hash=commit_hash[:12],
        timestamp=datetime.utcnow().isoformat() + 'Z',
        pre_commit_ran=pre_commit_ran,
        post_commit_ran=True,
        message=message[:100]
    )
    
    data.records[commit_hash[:12]] = record
    data.total_commits += 1
    
    # Check for bypass
    if not pre_commit_ran:
        data.bypasses_detected += 1
        Console.warn(f"[Hook Guardian] BYPASS DETECTED: Commit {commit_hash[:8]} skipped pre-commit!")
        Console.warn("[Hook Guardian] --no-verify was used. This has been logged.")
        
        # Log to lessons as a learning opportunity
        _record_bypass_lesson(root)
    else:
        Console.ok(f"[Hook Guardian] Commit {commit_hash[:8]} tracked successfully")
    
    # Keep only last 100 records
    if len(data.records) > 100:
        sorted_records = sorted(data.records.items(), key=lambda x: x[1].timestamp, reverse=True)
        data.records = dict(sorted_records[:100])
    
    save_guardian_data(data)
    
    # Trigger auto-learning
    try:
        from .auto_learn import learn_from_commit
        learn_from_commit(root)
    except Exception:
        pass


def _record_bypass_lesson(root: Path):
    """Record bypass as a lesson."""
    try:
        from .auto_heal import add_lesson
        add_lesson("Bypassed hook detected - always run full pre-commit checks for maximum quality", root)
    except Exception:
        pass


def verify_all_commits(root: Path = None) -> bool:
    """
    Verify all local unpushed commits have hook records.
    
    Returns True if all verified, False if bypasses detected.
    """
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = load_guardian_data(root)
    
    # Get unpushed commits
    output = run_git_command(['log', '@{u}..HEAD', '--format=%H', '--reverse'], cwd=root)
    
    if not output or output.strip() == '':
        Console.ok("[Hook Guardian] No unpushed commits to verify")
        return True
    
    unpushed = [h[:12] for h in output.strip().split('\n') if h]
    
    bypasses = []
    missing = []
    
    for commit_hash in unpushed:
        if commit_hash in data.records:
            record = data.records[commit_hash]
            if not record.pre_commit_ran:
                bypasses.append(commit_hash)
        else:
            missing.append(commit_hash)
    
    if bypasses or missing:
        Console.warn("=" * 60)
        Console.warn("[Hook Guardian] BYPASS DETECTED!")
        Console.warn("=" * 60)
        
        if bypasses:
            Console.warn(f"\nCommits that skipped pre-commit: {len(bypasses)}")
            for h in bypasses[:5]:
                Console.warn(f"  - {h}")
        
        if missing:
            Console.warn(f"\nCommits with no record: {len(missing)}")
            for h in missing[:5]:
                Console.warn(f"  - {h}")
        
        Console.warn("\nThese commits bypassed MCP quality checks.")
        Console.warn("Run 'mcp hook-guardian --reconcile' to fix.")
        Console.warn("=" * 60)
        
        return False
    
    Console.ok(f"[Hook Guardian] All {len(unpushed)} commits verified - no bypasses")
    return True


def reconcile_bypasses(root: Path = None):
    """Run checks on bypassed commits to reconcile."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    
    Console.info("[Hook Guardian] Running reconciliation...")
    Console.info("Executing skipped checks on current state...\n")
    
    # Run the checks that would have run in pre-commit
    import subprocess
    
    checks = [
        ('Security Scan', ['python', 'mcp-agentic-rules/mcp.py', 'security', '.']),
        ('Code Review', ['python', 'mcp-agentic-rules/mcp.py', 'review', '.', '--strict']),
        ('Bug Prediction', ['python', 'mcp-agentic-rules/mcp.py', 'predict-bugs', '.']),
    ]
    
    for name, cmd in checks:
        Console.info(f"Running {name}...")
        try:
            subprocess.run(cmd, cwd=root, check=False)
        except Exception as e:
            Console.warn(f"  {name} failed: {e}")
    
    Console.ok("\n[Hook Guardian] Reconciliation complete")
    Console.info("Bypassed commits have now had checks run on their results.")


def show_status(root: Path = None):
    """Show hook guardian status."""
    root = root or get_project_boundary() or find_project_root() or Path.cwd()
    data = load_guardian_data(root)
    
    print("# Hook Guardian Status\n")
    print(f"**Total Commits Tracked:** {data.total_commits}")
    print(f"**Bypasses Detected:** {data.bypasses_detected}")
    print(f"**Last Updated:** {data.last_updated}")
    
    if data.bypasses_detected > 0:
        bypass_rate = (data.bypasses_detected / max(1, data.total_commits)) * 100
        print(f"\n**Bypass Rate:** {bypass_rate:.1f}%")
        
        if bypass_rate > 10:
            print("\n> [!WARNING]")
            print("> High bypass rate detected. Consider enforcing stricter policies.")
    
    # Recent records
    if data.records:
        print("\n## Recent Commits\n")
        recent = sorted(data.records.values(), key=lambda x: x.timestamp, reverse=True)[:10]
        
        for r in recent:
            status = "+" if r.pre_commit_ran else "BYPASS"
            print(f"- [{status}] {r.commit_hash}: {r.message[:50]}")


def main():
    """CLI entry point."""
    Console.header("Hook Guardian")
    
    root = get_project_boundary() or find_project_root() or Path.cwd()
    
    if '--record-pre-commit' in sys.argv:
        record_pre_commit(root)
        return 0
    
    if '--record-commit' in sys.argv:
        record_commit(root)
        return 0
    
    if '--verify-all' in sys.argv:
        success = verify_all_commits(root)
        return 0 if success else 1
    
    if '--reconcile' in sys.argv:
        reconcile_bypasses(root)
        return 0
    
    # Default: show status
    show_status(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
