"""
Tests for Unlimited Context & Preemptive Automation Upgrade
===========================================================
"""

import sys
import os
import json
import tempfile
from pathlib import Path
import pytest

# Ensure scripts directory is in path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from scripts.dynamic_context import skeletonize_python, skeletonize_file, ContextBudgetEngine
from scripts.dependency_graph import MacroCodebaseGraph
from scripts.preemptive_daemon import PreemptiveDaemon
from scripts.memory import MemoryStore


@pytest.fixture
def temp_codebase():
    """Fixture creating a temporary codebase with dependencies to build a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # 1. Parent module (utils.py)
        utils_code = '''
class BaseUtility:
    """Base utility class."""
    def __init__(self):
        self.active = True

    def calculate(self, x: int) -> int:
        """Perform base calculation."""
        return x * 2
'''
        (root / "utils.py").write_text(utils_code, encoding="utf-8")

        # 2. Child module (service.py imports utils.py)
        service_code = '''
from utils import BaseUtility

class CustomService(BaseUtility):
    """Custom service inheriting from BaseUtility."""
    def run_service(self, val: str) -> str:
        """Run service logic."""
        res = self.calculate(10)
        return f"Result: {val} - {res}"
'''
        (root / "service.py").write_text(service_code, encoding="utf-8")

        # 3. Dummy main (app.py imports service.py)
        app_code = '''
import sys
from service import CustomService

def main():
    service = CustomService()
    print(service.run_service("hello"))

if __name__ == '__main__':
    main()
'''
        (root / "app.py").write_text(app_code, encoding="utf-8")

        yield root


def test_dynamic_context_skeletonizer():
    """Test Python AST skeletonization (Linguistic Zoom Level 1)."""
    code = '''
class Foo:
    """Class docstring."""
    def __init__(self, val):
        self.val = val
        print("initializing")

    def run(self):
        """Run function docstring."""
        x = 10
        y = 20
        return x + y

def bar(name: str):
    """Bar function docstring."""
    print("hello " + name)
    return True
'''
    skeleton = skeletonize_python(code)
    
    # Assertions
    assert "class Foo" in skeleton
    assert '"""Class docstring."""' in skeleton
    assert '"""Run function docstring."""' in skeleton
    assert '"""Bar function docstring."""' in skeleton
    assert "... [body compressed] ..." in skeleton
    # Method bodies should be stripped out
    assert "print(\"initializing\")" not in skeleton
    assert "x = 10" not in skeleton
    assert 'print("hello " + name)' not in skeleton


def test_context_budget_engine():
    """Test token budgeting & dynamic downgrading."""
    engine = ContextBudgetEngine(token_budget=1000)
    limits = engine.get_limits()
    
    assert "active" in limits
    assert limits["active"] == 450  # 45% of 1000
    
    # Mock files: (path_str, raw_content, priority)
    # File 1: High priority, small -> keeps full detail (priority 0)
    # File 2: High priority, huge -> compressed to AST skeleton or truncated to fit budget
    huge_content = "\n".join([f"def func_{i}():\n    print({i})" for i in range(100)])
    files = [
        ("utils.py", "def small_func():\n    return 42", 0),
        ("huge_service.py", huge_content, 0)
    ]
    
    budgeted = engine.format_and_budget_files(files, target_budget=300)
    
    # We should have both files, but the huge one should have been skeletonized/truncated to fit the 300 target
    assert len(budgeted) == 2
    assert budgeted[0][0] == "utils.py"
    assert "small_func" in budgeted[0][1]
    
    assert budgeted[1][0] == "huge_service.py"
    assert any(x in budgeted[1][1] for x in ("... [body compressed]", "[collapsed for budget]", "truncated", "Summary"))


def test_dependency_graph_building(temp_codebase):
    """Test macro codebase graph build and ripple impact evaluation."""
    graph = MacroCodebaseGraph(root=temp_codebase)
    data = graph.build()
    
    assert "utils.py" in data["files"]
    assert "service.py" in data["files"]
    assert "app.py" in data["files"]
    
    # Verify inheritance extraction
    assert "CustomService" in graph.inheritance
    assert graph.inheritance["CustomService"] == "BaseUtility"
    
    # Verify dependents resolution
    assert "service.py" in graph.dependents.get("utils.py", set())
    assert "app.py" in graph.dependents.get("service.py", set())
    
    # Ripple impact of modified utils.py should downstream to service.py and app.py
    ripples = graph.get_ripple_impact("utils.py")
    assert "service.py" in ripples
    assert "app.py" in ripples
    
    # Ripple impact of service.py should downstream to app.py
    ripples_service = graph.get_ripple_impact("service.py")
    assert "app.py" in ripples_service
    assert "utils.py" not in ripples_service


def test_preemptive_daemon_health(temp_codebase):
    """Test preemptive daemon initialization and status management."""
    # Start and stop daemon (ensure no threading deadlocks)
    PreemptiveDaemon.start(root=temp_codebase)
    health = PreemptiveDaemon.get_health()
    
    assert "status" in health
    assert "Active" in health["status"] or "Initializing" in health["status"]
    
    # Change status manually on a different key to avoid background loop race condition
    PreemptiveDaemon.set_health_status("custom_test_status", "Testing Manual Status")
    health = PreemptiveDaemon.get_health()
    assert health["custom_test_status"] == "Testing Manual Status"
    
    # Verify file is written
    health_file = temp_codebase / '.mcp' / 'active_health.json'
    assert health_file.exists()
    
    # Shutdown
    PreemptiveDaemon.stop()
    assert not PreemptiveDaemon.active


def test_vectorized_activity_ledger():
    """Test SQLite persistent activity ledger insertion and retrieval."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        db_path = db_dir / "knowledge.db"
        
        # Initialize Memory DB
        memory = MemoryStore(storage_path=db_dir)
        
        # Assert table created successfully
        cursor = memory.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activity_ledger'")
        assert cursor.fetchone() is not None
        
        # Record agent action
        action_id = memory.record_agent_action(
            tool_name="semantic_search",
            args='{"query": "database connection"}',
            status="success",
            summary="Found SQLite connection string in db_handler.py"
        )
        assert action_id > 0
        
        # Record another action
        memory.record_agent_action(
            tool_name="replace_file_content",
            args='{"file": "main.py"}',
            status="success",
            summary="Refactored main startup loop"
        )
        
        # Search activity stream
        results = memory.search_activity_stream(query="SQLite")
        assert len(results) >= 1
        assert results[0]["tool_name"] == "semantic_search"
        assert "Found SQLite" in results[0]["summary"]
        
        # General fetch all
        all_actions = memory.search_activity_stream(query="", limit=10)
        assert len(all_actions) == 2
        
        # Close connection explicitly to release Windows file lock
        memory.conn.close()
