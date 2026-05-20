"""
System Diagnostics and Auto-Repair Utility (MCP Doctor)
======================================================
Verifies that all components of mcp-agentic-context are correctly installed and running.
Offers automated repairs for common configuration issues.

Usage:
    python mcp.py doctor
    python mcp.py doctor --fix
    python mcp.py doctor --json
"""

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .utils import Console, find_project_root

def run_cmd(cmd: list, cwd: Path = None) -> tuple:
    """Run a shell command and return status, stdout, stderr."""
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


class Doctor:
    """Diagnostic coordinator."""

    def __init__(self, root: Path = None):
        self.root = root or find_project_root() or Path.cwd()
        self.issues = []
        self.fixes_applied = []

    def check_python_env(self) -> dict:
        """Verify Python environment and required modules."""
        venv_path = os.environ.get('VIRTUAL_ENV') or sys.prefix
        is_in_venv = venv_path != sys.base_prefix

        # Check key libraries
        libs = {}
        for lib in ['sqlite3', 'torch', 'sentence_transformers']:
            try:
                __import__(lib)
                libs[lib] = "Available"
            except ImportError:
                libs[lib] = "Not installed"

        status = "ok"
        message = "Python environment is healthy"
        if not is_in_venv:
            status = "warn"
            message = "Not running inside a virtual environment"
            self.issues.append(('venv', "Run inside a virtual environment for isolated dependencies"))

        missing_libs = [k for k, v in libs.items() if v == "Not installed" and k != 'sentence_transformers']
        if missing_libs:
            status = "error"
            message = f"Missing required libraries: {', '.join(missing_libs)}"
            self.issues.append(('libs', f"Install missing required packages: pip install {', '.join(missing_libs)}"))

        return {
            "name": "Python Environment",
            "status": status,
            "message": message,
            "details": {
                "version": sys.version.split()[0],
                "venv_path": venv_path,
                "is_in_venv": is_in_venv,
                "libraries": libs
            }
        }

    def check_git(self) -> dict:
        """Verify Git setup and hooks."""
        # Check if inside a git repository
        code, out, _ = run_cmd(['git', 'rev-parse', '--is-inside-work-tree'], self.root)
        is_repo = (code == 0 and out == 'true')

        if not is_repo:
            self.issues.append(('git_repo', "Current directory is not a Git repository. Run 'git init' first."))
            return {
                "name": "Git Repository",
                "status": "error",
                "message": "Not a Git repository",
                "details": {"is_repo": False}
            }

        # Resolve actual git folder
        code, out, _ = run_cmd(['git', 'rev-parse', '--git-common-dir'], self.root)
        if code == 0:
            git_dir = Path(out).resolve() if os.path.isabs(out) else (self.root / out).resolve()
        else:
            git_dir = self.root / '.git'

        # Check commit count
        code, out, _ = run_cmd(['git', 'rev-list', '--count', 'HEAD'], self.root)
        commit_count = int(out) if code == 0 and out.isdigit() else 0

        # Check hooks
        pre_commit = git_dir / 'hooks' / 'pre-commit'
        post_commit = git_dir / 'hooks' / 'post-commit'

        hooks_installed = False
        if pre_commit.exists() and post_commit.exists():
            try:
                content = pre_commit.read_text(encoding='utf-8', errors='ignore')
                if 'mcp' in content or 'mcp-agentic-context' in content:
                    hooks_installed = True
            except Exception:
                pass

        status = "ok"
        message = "Git hooks are correctly configured"
        if not hooks_installed:
            status = "error"
            message = "Git pre-commit/post-commit hooks are not installed or inactive"
            self.issues.append(('git_hooks', "Git automation hooks are missing. Run 'mcp setup --hooks' to install."))

        return {
            "name": "Git Integration",
            "status": status,
            "message": message,
            "details": {
                "is_repo": True,
                "commit_count": commit_count,
                "pre_commit_exists": pre_commit.exists(),
                "post_commit_exists": post_commit.exists(),
                "hooks_configured": hooks_installed
            }
        }

    def check_memory_db(self) -> dict:
        """Verify SQLite persistent memory database."""
        home = Path.home()
        memory_dir = home / '.mcp' / 'memory'
        db_path = memory_dir / 'knowledge.db'

        if not db_path.exists():
            self.issues.append(('memory_db', "SQLite persistent memory file not found. It will be initialized on first run."))
            return {
                "name": "Persistent Memory",
                "status": "warn",
                "message": "Database file does not exist yet",
                "details": {"db_exists": False}
            }

        status = "ok"
        message = "Memory database is online and healthy"
        memories_count = 0
        wal_enabled = False

        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            # Check WAL mode
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            wal_enabled = journal_mode.lower() == 'wal'

            # Get counts
            cursor.execute("SELECT COUNT(*) FROM memories")
            memories_count = cursor.fetchone()[0]
            conn.close()
        except Exception as e:
            status = "error"
            message = f"Failed to connect to database: {e}"
            self.issues.append(('db_corrupt', "SQLite database may be locked or corrupt. Try removing it or repairing database."))

        return {
            "name": "Persistent Memory DB",
            "status": status,
            "message": message,
            "details": {
                "db_exists": True,
                "db_path": str(db_path),
                "memories_count": memories_count,
                "wal_enabled": wal_enabled
            }
        }

    def check_indexes(self) -> dict:
        """Check all 7 codebase indexes."""
        mcp_dir = self.root / '.mcp'
        summary_path = mcp_dir / 'index_summary.json'

        if not summary_path.exists():
            self.issues.append(('index_missing', "Codebase has not been indexed yet. Run 'mcp index-all' to initialize codebase intelligence."))
            return {
                "name": "Codebase Indexes",
                "status": "error",
                "message": "Indexes are not built",
                "details": {"indexed": False}
            }

        last_indexed_time = "Unknown"
        elapsed_str = "Never"
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            last_indexed_time = summary.get('timestamp', 'Unknown')
            if last_indexed_time != 'Unknown':
                # Convert ISO string
                ts = last_indexed_time.replace('Z', '+00:00')
                dt = datetime.fromisoformat(ts)
                diff = time.time() - dt.timestamp()
                if diff < 60:
                    elapsed_str = "Less than a minute ago"
                elif diff < 3600:
                    elapsed_str = f"{int(diff/60)} minutes ago"
                elif diff < 86400:
                    elapsed_str = f"{int(diff/3600)} hours ago"
                else:
                    elapsed_str = f"{int(diff/86400)} days ago"
        except Exception:
            pass

        indexes = {
            'Semantic Code': ('vector_index/chunks.json', False),
            'Git History': ('git_index.json', True),
            'TODOs/FIXMEs': ('todo_index.json', True),
            'Impact Graph': ('impact_graph.json', True),
            'Documentation': ('doc_index.json', True),
            'Config': ('config_index.json', True),
            'Coverage': ('coverage_index.json', True)
        }

        details = {}
        missing = []
        for idx_name, (sub_path, is_file) in indexes.items():
            path = mcp_dir / sub_path
            exists = path.exists()
            size = path.stat().st_size if exists else 0
            details[idx_name] = {
                "exists": exists,
                "size_bytes": size
            }
            # Coverage is optional, git/impact can be missing in non-git directories, but others are core
            if not exists and idx_name in ('Semantic Code', 'TODOs/FIXMEs', 'Impact Graph'):
                missing.append(idx_name)

        status = "ok"
        message = f"Indexes are healthy. Last updated: {elapsed_str}."
        if missing:
            status = "warn"
            message = f"Some core indexes are missing: {', '.join(missing)}"
            self.issues.append(('index_partial', "Some codebase indexes are missing. Run 'mcp index-all' to rebuild them."))

        return {
            "name": "Codebase Indexes",
            "status": status,
            "message": message,
            "details": {
                "indexed": True,
                "last_indexed": last_indexed_time,
                "last_indexed_relative": elapsed_str,
                "individual_indexes": details
            }
        }

    def check_project_packs(self) -> dict:
        """Verify project packs."""
        packs_dir = self.root / 'project_packs'
        exists = packs_dir.exists()

        packs = []
        if exists:
            try:
                for item in packs_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        packs.append(item.name)
            except Exception:
                pass

        status = "ok"
        message = f"Found {len(packs)} available project packs"
        if not exists or not packs:
            status = "warn"
            message = "No project packs directory found"
            self.issues.append(('project_packs', "No project packs available. Restore project_packs folder from repository."))

        return {
            "name": "Project Packs",
            "status": status,
            "message": message,
            "details": {
                "exists": exists,
                "packs": packs
            }
        }

    def run_all(self) -> list:
        """Run all diagnostic checks."""
        self.issues = []
        return [
            self.check_python_env(),
            self.check_git(),
            self.check_memory_db(),
            self.check_indexes(),
            self.check_project_packs()
        ]

    def repair(self) -> bool:
        """Attempt to auto-fix identified issues."""
        self.fixes_applied = []
        if not self.issues:
            return True

        # Re-fetch issues to ensure we have current list
        self.run_all()

        mcp_script = self.root / 'mcp-agentic-rules' / 'mcp.py'

        # 1. Handle git_repo initialization first so hooks can be installed in the same run
        git_repo_issue = next((i for i in self.issues if i[0] == 'git_repo'), None)
        if git_repo_issue:
            Console.info("Attempting to initialize Git repository...")
            code, _, err = run_cmd(['git', 'init'], self.root)
            if code == 0:
                self.fixes_applied.append("Initialized a new Git repository in the project root.")
                Console.ok("Git repository initialized successfully.")
                # Re-run diagnostics so git_hooks is added to self.issues
                self.run_all()
            else:
                Console.warn(f"Failed to initialize Git repository: {err}")

        # 2. Process all other issues
        for issue_type, desc in list(self.issues):
            if issue_type == 'git_hooks':
                Console.info("Attempting to repair Git hooks...")
                code, _, err = run_cmd([sys.executable, str(mcp_script), 'setup', '--hooks'], self.root)
                if code == 0:
                    self.fixes_applied.append("Installed Git pre-commit and post-commit hooks successfully.")
                    Console.ok("Git hooks repaired successfully.")
                else:
                    Console.warn(f"Failed to repair Git hooks: {err}")

            elif issue_type == 'index_missing' or issue_type == 'index_partial':
                Console.info("Attempting to repair codebase indexes...")
                code, _, err = run_cmd([sys.executable, str(mcp_script), 'index-all'], self.root)
                if code == 0:
                    self.fixes_applied.append("Rebuilt all codebase intelligence indexes incrementally.")
                    Console.ok("Codebase indexes repaired successfully.")
                else:
                    Console.warn(f"Failed to build codebase indexes: {err}")

        # Run checks again
        self.run_all()
        return len(self.issues) == 0


def main():
    """Main CLI handler."""
    root = find_project_root() or Path.cwd()
    doctor = Doctor(root)

    # Check arguments
    is_json = '--json' in sys.argv
    is_fix = '--fix' in sys.argv

    if is_json:
        # Silently run all checks and dump JSON
        results = doctor.run_all()
        health_score = 100
        errors = sum(1 for r in results if r['status'] == 'error')
        warns = sum(1 for r in results if r['status'] == 'warn')
        health_score = max(0, 100 - (errors * 25) - (warns * 10))

        output = {
            "health_score": health_score,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "root": str(root),
            "diagnostics": results,
            "issues": [{"type": i[0], "description": i[1]} for i in doctor.issues],
            "fixes_applied": doctor.fixes_applied
        }
        print(json.dumps(output, indent=2))
        return 0

    Console.header("MCP Global Diagnostics (Doctor)")
    print(f"Project root: {root}\n")

    results = doctor.run_all()

    # Print checklist
    errors_count = 0
    warns_count = 0

    for result in results:
        status = result['status']
        name = result['name']
        msg = result['message']

        if status == 'ok':
            Console.ok(f"{name:20} - [OK] {msg}")
        elif status == 'warn':
            Console.warn(f"{name:20} - [WARN] {msg}")
            warns_count += 1
        else:
            Console.fail(f"{name:20} - [FAIL] {msg}")
            errors_count += 1

    print("")

    if doctor.issues:
        print("Identified Issues:")
        for idx, (issue_type, desc) in enumerate(doctor.issues):
            print(f"  {idx + 1}. [{issue_type.upper()}] {desc}")
        print("")

    if is_fix:
        if not doctor.issues:
            Console.ok("No issues detected. Nothing to repair.")
            return 0

        Console.info("Running automated repairs...")
        success = doctor.repair()
        print("")
        
        if doctor.fixes_applied:
            print("Repairs Applied:")
            for fix in doctor.fixes_applied:
                print(f"  * {fix}")
            print("")

        if success:
            Console.ok("All repairable issues resolved successfully!")
        else:
            Console.warn(f"Some issues require manual intervention. Remaining issues: {len(doctor.issues)}")
    else:
        if errors_count > 0:
            Console.fail(f"Diagnostics complete: found {errors_count} errors and {warns_count} warnings.")
            print("Tip: Run 'python mcp.py doctor --fix' to automatically repair resolved issues.")
            return 1
        elif warns_count > 0:
            Console.warn(f"Diagnostics complete: found {warns_count} warnings.")
            print("Tip: Run 'python mcp.py doctor --fix' to automatically resolve common warnings.")
            return 0
        else:
            Console.ok("All systems operational. Diagnostics healthy (100/100).")
            return 0


if __name__ == '__main__':
    sys.exit(main())
