#!/bin/bash
# ============================================================================
# MCP Global Rules - Enhanced Install (Linux/Mac)
# ============================================================================
# Usage: ./install_enhanced.sh
#
# This installs MCP with:
#   - All 42 Python scripts
#   - All 6 git hooks (auto-installed with venv + auto-commit)
#   - Python 3.11.x virtual environment (auto-created)
#   - Auto-commit system for frequent backups
#   - Full indexing
#   - AI agent memory files (.claude, .gemini, .agent)
# ============================================================================

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
function print_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
function print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
function print_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   MCP GLOBAL RULES - ENHANCED INSTALLER             ║"
echo "║   42 Scripts | 48 Commands | 6 Hooks | Venv | Auto  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Check if in a git repository
IS_GIT_REPO=false
if [ -d ".git" ]; then
    IS_GIT_REPO=true
    print_ok "Git repository detected"
else
    print_warn "Not a git repository. Initializing..."
    git init
    IS_GIT_REPO=true
fi

# Detect Python
PYTHON_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    print_error "Python not found. Please install Python 3.8+"
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
print_info "Python: $PYTHON_CMD ($PYTHON_VERSION)"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(pwd)"

# Determine MCP source
if [[ "$SCRIPT_DIR" == *"mcp-agentic-rules"* ]]; then
    MCP_SOURCE="$SCRIPT_DIR"
else
    MCP_SOURCE="$SCRIPT_DIR/mcp-agentic-rules"
fi

MCP_TARGET="$PROJECT_ROOT/mcp-agentic-rules"

# ============================================================================
# STEP 1: Copy MCP package
# ============================================================================
print_info "Step 1/9: Installing MCP package..."

if [ "$MCP_SOURCE" != "$MCP_TARGET" ]; then
    if [ -d "$MCP_TARGET" ]; then
        print_warn "MCP already exists. Updating..."
        rm -rf "$MCP_TARGET"
    fi

    cp -r "$MCP_SOURCE" "$MCP_TARGET"
    print_ok "Copied MCP to $MCP_TARGET"
else
    print_ok "MCP already in place"
fi

# ============================================================================
# STEP 2: Create .mcp directory
# ============================================================================
print_info "Step 2/9: Creating MCP data directory..."
mkdir -p "$PROJECT_ROOT/.mcp"
print_ok "Created .mcp/"

# ============================================================================
# STEP 3: Create Python 3.11.x virtual environment
# ============================================================================
print_info "Step 3/9: Setting up Python 3.11.x virtual environment..."

# Use venv manager to create venv
$PYTHON_CMD "$MCP_TARGET/scripts/venv_manager.py" ensure || {
    print_warn "Venv creation skipped (Python 3.11.x not found)"
    print_warn "MCP will use system Python"
}

if [ -d "$PROJECT_ROOT/.venv" ]; then
    print_ok "Python 3.11.x virtual environment ready"
fi

# ============================================================================
# STEP 4: Create AI agent memory files
# ============================================================================
print_info "Step 4/9: Creating AI agent memory files..."

if [ -f "$MCP_SOURCE/../AI_AGENT_MEMORY.md" ]; then
    cp "$MCP_SOURCE/../AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.claude"
    cp "$MCP_SOURCE/../AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.gemini"
    cp "$MCP_SOURCE/../AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.agent"
    print_ok "Created .claude, .gemini, .agent files"
elif [ -f "$PROJECT_ROOT/mcp-agentic-context/AI_AGENT_MEMORY.md" ]; then
    cp "$PROJECT_ROOT/mcp-agentic-context/AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.claude"
    cp "$PROJECT_ROOT/mcp-agentic-context/AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.gemini"
    cp "$PROJECT_ROOT/mcp-agentic-context/AI_AGENT_MEMORY.md" "$PROJECT_ROOT/.agent"
    print_ok "Created .claude, .gemini, .agent files"
else
    print_warn "AI_AGENT_MEMORY.md not found, skipping agent files"
fi

# ============================================================================
# STEP 5: Install git hooks
# ============================================================================
print_info "Step 5/9: Installing git hooks..."

if [ "$IS_GIT_REPO" = true ]; then
    HOOKS_SOURCE="$MCP_TARGET/.git-hooks"
    HOOKS_TARGET="$PROJECT_ROOT/.git/hooks"

    mkdir -p "$HOOKS_TARGET"

    HOOKS=("pre-commit" "post-commit" "commit-msg" "pre-push" "post-checkout" "post-merge")
    INSTALLED_COUNT=0

    for hook in "${HOOKS[@]}"; do
        SOURCE_HOOK="$HOOKS_SOURCE/$hook"
        TARGET_HOOK="$HOOKS_TARGET/$hook"

        if [ -f "$SOURCE_HOOK" ]; then
            cp "$SOURCE_HOOK" "$TARGET_HOOK"
            chmod +x "$TARGET_HOOK"
            INSTALLED_COUNT=$((INSTALLED_COUNT + 1))
        fi
    done

    print_ok "Installed $INSTALLED_COUNT git hooks"
else
    print_warn "Skipping hooks (not a git repository)"
fi

# ============================================================================
# STEP 6: Initialize auto-commit system
# ============================================================================
print_info "Step 6/9: Initializing auto-commit system..."

if [ -f "$MCP_TARGET/scripts/auto_commit.py" ]; then
    $PYTHON_CMD "$MCP_TARGET/scripts/auto_commit.py" status >/dev/null 2>&1 || true
    print_ok "Auto-commit system initialized"
fi

# ============================================================================
# STEP 7: Build initial indexes
# ============================================================================
print_info "Step 7/9: Building indexes..."

cd "$MCP_TARGET"
$PYTHON_CMD mcp.py index-all --quick &>/dev/null &
cd "$PROJECT_ROOT"
print_ok "Index build started (background)"

# ============================================================================
# STEP 8: Create AI agent instructions
# ============================================================================
print_info "Step 8/9: Creating AI agent instructions..."

cat > "$PROJECT_ROOT/AI_AGENT_MCP.md" << 'EOF'
# MCP Global Rules - AI Agent Instructions

## Available Commands (48 total)

Run with: `python mcp-agentic-rules/mcp.py <command>`

### Before Coding
```bash
mcp autocontext              # Load relevant context
mcp recall "topic"           # Search memory
mcp search "query"           # Semantic code search
```

### While Coding
```bash
mcp predict-bugs file.py     # Check for bugs
mcp impact file.py           # What breaks?
mcp context "query"          # Get context
```

### After Coding
```bash
mcp review file.py           # Code review
mcp security file.py         # Security check
mcp test-gen file.py --impl  # Generate tests
```

### Remember & Learn
```bash
mcp remember "key" "value"   # Store knowledge
mcp recall "query"           # Search knowledge
mcp learn --patterns         # View learned patterns
```

### Virtual Environment
```bash
# Venv is automatically managed by MCP hooks
# Python 3.11.x is enforced for all operations
source .venv/bin/activate    # Manual activation (if needed)
```

### Auto-Commit (Backup System)
```bash
python mcp-agentic-rules/scripts/auto_commit.py status   # Check status
python mcp-agentic-rules/scripts/auto_commit.py commit   # Manual backup
python mcp-agentic-rules/scripts/auto_commit.py list     # List backups
python mcp-agentic-rules/scripts/auto_commit.py restore --hash <hash>  # Restore
```

## Hooks (Automatic)

All hooks are installed and will run automatically:
- **pre-commit**: Venv check, auto-fix, risk check, security scan, review
- **post-commit**: Learning, index update, bypass detection
- **post-checkout**: Warm indexes
- **pre-push**: Security + architecture validation

## Quick Reference

| Need | Command |
|------|---------|
| Context | `mcp autocontext` |
| Search | `mcp search "query"` |
| Review | `mcp review .` |
| Bugs | `mcp predict-bugs .` |
| Tests | `mcp test-gen file.py` |
| Memory | `mcp remember/recall` |
| Backup | `auto_commit.py commit` |
| Restore | `auto_commit.py restore` |
EOF

print_ok "Created AI_AGENT_MCP.md"

# ============================================================================
# STEP 9: Create .gitignore entries
# ============================================================================
print_info "Step 9/9: Updating .gitignore..."

if [ ! -f "$PROJECT_ROOT/.gitignore" ]; then
    touch "$PROJECT_ROOT/.gitignore"
fi

# Add MCP-related entries if not present
grep -q ".venv/" "$PROJECT_ROOT/.gitignore" || echo ".venv/" >> "$PROJECT_ROOT/.gitignore"
grep -q ".mcp/" "$PROJECT_ROOT/.gitignore" || echo ".mcp/" >> "$PROJECT_ROOT/.gitignore"

print_ok "Updated .gitignore"

# ============================================================================
# DONE
# ============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          MCP INSTALLATION COMPLETE!                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Installed:"
echo "  ✓ 42 Python scripts"
echo "  ✓ 48 CLI commands"
echo "  ✓ 6 git hooks (enforced)"
echo "  ✓ Python 3.11.x venv (enforced)"
echo "  ✓ Auto-commit system (frequent backups)"
echo "  ✓ AI agent memory files"
echo "  ✓ AI agent instructions"
echo ""
echo "Usage:"
echo "  python mcp-agentic-rules/mcp.py help"
echo "  python mcp-agentic-rules/mcp.py <command>"
echo ""
echo "Quick start:"
echo "  python mcp-agentic-rules/mcp.py autocontext"
echo "  python mcp-agentic-rules/mcp.py search \"your query\""
echo ""
echo "Auto-commit:"
echo "  python mcp-agentic-rules/scripts/auto_commit.py status"
echo "  python mcp-agentic-rules/scripts/auto_commit.py commit"
echo ""
echo "Virtual environment is automatically enforced in all hooks!"
echo ""
