"""
MCP Preemptive Background Automation Daemon
===========================================
Monitors file modifications, performs preemptive background syntax checks,
runs affected unit tests, and compiles real-time active health metrics.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Set, Any, Optional

from .utils import find_project_root, Console
from .dependency_graph import MacroCodebaseGraph


class PreemptiveDaemon:
    """
    Lightweight background worker daemon.
    Runs active health checks, syntax audits, and affected tests when files change.
    """
    _thread: Optional[threading.Thread] = None
    _lock = threading.Lock()
    active = False
    root_dir: Optional[Path] = None
    
    # State tracking
    file_mtimes: Dict[str, float] = {}
    health_status: Dict[str, Any] = {
        "status": "Initializing",
        "last_checked": "",
        "syntax_errors": [],
        "test_results": {
            "status": "Healthy",
            "passed": 0,
            "failed": 0,
            "failures": [],
            "logs": ""
        },
        "ripple_warnings": []
    }

    @classmethod
    def get_health(cls) -> dict:
        """Retrieve thread-safe active health report."""
        with cls._lock:
            return dict(cls.health_status)

    @classmethod
    def set_health_status(cls, key: str, value: Any):
        """Thread-safe update of health status details."""
        with cls._lock:
            cls.health_status[key] = value
            
        # Write to active_health.json
        try:
            root = cls.root_dir or find_project_root() or Path.cwd()
            out_path = root / '.mcp' / 'active_health.json'
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(cls.health_status, f, indent=2)
        except Exception:
            pass

    @classmethod
    def start(cls, root: Path = None):
        """Start the preemptive daemon loop thread."""
        with cls._lock:
            if cls.active:
                return
            cls.active = True
            
        cls.root_dir = root or find_project_root() or Path.cwd()
        root = cls.root_dir
        
        def run_loop():
            # 1. Warm file timestamps
            cls._scan_file_timestamps(root)
            
            # 2. Build or load dependency graph
            graph = MacroCodebaseGraph(root)
            graph.build()
            
            cls.set_health_status("status", "Active (Monitoring)")
            cls.set_health_status("last_checked", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

            while True:
                # Sleep interval in small chunks to support fast shutdown
                shutdown_detected = False
                for _ in range(40):
                    time.sleep(0.1)
                    with cls._lock:
                        if not cls.active:
                            shutdown_detected = True
                            break
                if shutdown_detected:
                    break
                
                # Check if any source files changed
                changed_files = cls._get_changed_files(root)
                if changed_files:
                    cls.set_health_status("status", "Analyzing Changes...")
                    
                    # A. Rebuild structural dependency graph
                    try:
                        graph.build()
                    except Exception:
                        pass
                    
                    # B. Check syntax issues in changed files
                    syntax_errors = cls._check_syntax(changed_files)
                    cls.set_health_status("syntax_errors", syntax_errors)
                    
                    # C. Run downstream impacted/affected tests
                    cls._run_affected_tests(root, changed_files, graph)
                    
                    cls.set_health_status("status", "Active (Monitoring)")
                    cls.set_health_status("last_checked", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

        cls._thread = threading.Thread(target=run_loop, name="MCP-PreemptiveDaemon", daemon=True)
        cls._thread.start()

    @classmethod
    def stop(cls):
        """Stop the preemptive daemon thread gracefully."""
        with cls._lock:
            cls.active = False
        if cls._thread and cls._thread.is_alive():
            cls._thread.join(timeout=3.0)

    @classmethod
    def _scan_file_timestamps(cls, root: Path):
        """Scans project files and registers initial modification timestamps."""
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.mcp', 'build', 'dist'}
        supported_exts = ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.cpp', '.hpp', '.c', '.h')
        
        try:
            for p in root.rglob('*'):
                if p.is_file() and p.suffix.lower() in supported_exts:
                    if not any(exclude in p.parts for exclude in exclude_dirs):
                        cls.file_mtimes[str(p)] = p.stat().st_mtime
        except Exception:
            pass

    @classmethod
    def _get_changed_files(cls, root: Path) -> List[Path]:
        """Compares timestamps and detects newly added or modified source files."""
        exclude_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.mcp', 'build', 'dist'}
        supported_exts = ('.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.cpp', '.hpp', '.c', '.h')
        
        changed = []
        try:
            current_paths = set()
            for p in root.rglob('*'):
                if p.is_file() and p.suffix.lower() in supported_exts:
                    if not any(exclude in p.parts for exclude in exclude_dirs):
                        p_str = str(p)
                        current_paths.add(p_str)
                        mtime = p.stat().st_mtime
                        if p_str not in cls.file_mtimes or cls.file_mtimes[p_str] != mtime:
                            cls.file_mtimes[p_str] = mtime
                            changed.append(p)
            
            # Detect deletions
            deleted_keys = [k for k in cls.file_mtimes.keys() if k not in current_paths]
            for k in deleted_keys:
                cls.file_mtimes.pop(k, None)
                
        except Exception:
            pass
            
        return changed

    @classmethod
    def _check_syntax(cls, files: List[Path]) -> List[dict]:
        """Performs preemptive syntax compilation tests on changed files."""
        errors = []
        for path in files:
            if path.suffix.lower() == '.py':
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        source = f.read()
                    import ast
                    ast.parse(source, filename=str(path))
                except SyntaxError as e:
                    errors.append({
                        "file": str(path.name),
                        "line": e.lineno,
                        "offset": e.offset,
                        "text": e.text.strip() if e.text else "",
                        "error": str(e.msg)
                    })
        return errors

    @classmethod
    def _run_affected_tests(cls, root: Path, changed_files: List[Path], graph: MacroCodebaseGraph):
        """Identifies affected test cases and runs them asynchronously in background."""
        # Find which test files in the codebase are impacted
        impacted_tests: Set[Path] = set()
        
        # 1. Look for test files directly modified
        for f in changed_files:
            if f.name.startswith('test_') or f.name.endswith('_test.py'):
                impacted_tests.add(f)
                
        # 2. Look for downstream test files affected by source modules
        for f in changed_files:
            if not (f.name.startswith('test_') or f.name.endswith('_test.py')):
                rel_path = str(f.relative_to(root)).replace('\\', '/')
                ripples = graph.get_ripple_impact(rel_path)
                
                # Check which of the ripple targets are actual test files
                for rip in ripples:
                    rip_path = root / rip
                    if rip_path.exists() and (rip_path.name.startswith('test_') or rip_path.name.endswith('_test.py')):
                        impacted_tests.add(rip_path)

        if not impacted_tests:
            # Check if there are general test files in root we can run as fallback
            test_files = list(root.glob('test_*.py')) + list(root.glob('tests/test_*.py'))
            if test_files:
                # Just run the first 2 tests as generic sanity checkpoints
                impacted_tests.update(test_files[:2])

        if not impacted_tests:
            cls.set_health_status("test_results", {
                "status": "No Tests Found",
                "passed": 0,
                "failed": 0,
                "failures": [],
                "logs": "No unit tests (test_*.py) detected in this workspace."
            })
            return

        cls.set_health_status("status", "Running Affected Tests...")
        
        passed_count = 0
        failed_count = 0
        failures = []
        all_logs = []

        for test_file in list(impacted_tests)[:4]: # Limit to max 4 test files to keep it extremely fast
            rel_test = str(test_file.relative_to(root))
            all_logs.append(f"=== Running test suite: {rel_test} ===")
            
            try:
                # Run test using sys.executable to preserve environment mappings
                proc = subprocess.run(
                    [sys.executable, "-m", "unittest", rel_test],
                    cwd=str(root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=15.0
                )
                
                all_logs.append(proc.stdout)
                
                if proc.returncode == 0:
                    passed_count += 1
                else:
                    failed_count += 1
                    failures.append(test_file.name)
            except subprocess.TimeoutExpired:
                all_logs.append(f"[TIMEOUT] Test took longer than 15 seconds to run.")
                failed_count += 1
                failures.append(test_file.name)
            except Exception as e:
                all_logs.append(f"[ERROR] Failed to execute test: {e}")
                failed_count += 1
                failures.append(test_file.name)

        status_str = "Healthy" if failed_count == 0 else "Unhealthy"
        cls.set_health_status("test_results", {
            "status": status_str,
            "passed": passed_count,
            "failed": failed_count,
            "failures": failures,
            "logs": "\n".join(all_logs)
        })

        # Set downstream ripple warnings context
        cls._compile_ripple_warnings(root, changed_files, graph)

    @classmethod
    def _compile_ripple_warnings(cls, root: Path, changed_files: List[Path], graph: MacroCodebaseGraph):
        """Compiles warnings explaining exactly what downstream files are impacted by changes."""
        warnings = []
        for f in changed_files:
            if not (f.name.startswith('test_') or f.name.endswith('_test.py')):
                rel_path = str(f.relative_to(root)).replace('\\', '/')
                ripples = graph.get_ripple_impact(rel_path)
                if ripples:
                    warnings.append({
                        "modified_file": f.name,
                        "impacted_count": len(ripples),
                        "impacted_files": ripples[:5] # Show top 5 impacted downstream targets
                    })
        cls.set_health_status("ripple_warnings", warnings)
