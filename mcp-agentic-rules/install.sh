#!/bin/bash
# ============================================================================
# MCP Global Rules - Single Command Install
# ============================================================================
# Usage: ./install.sh
#        curl -sSL https://example.com/mcp/install.sh | bash
#
# This installs MCP to the current project with:
#   - All 42 Python scripts
#   - All 6 git hooks (auto-installed)
#   - Full indexing
#   - AI agent instructions
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
ok() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          MCP GLOBAL RULES INSTALLER                  ║${NC}"
echo -e "${CYAN}║          42 Scripts | 50 Commands | 6 Hooks          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# Parse parameters
PACK=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --pack|-p) PACK="$2"; shift ;;
        *) ;;
    esac
    shift
done

# Check if in a git repository
if [ ! -d ".git" ]; then
    warn "Not a git repository. Some features will be limited."
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Detect Python
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    fail "Python not found. Please install Python 3.8+"
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
info "Python: $PYTHON_CMD ($PYTHON_VERSION)"

if [ "$PYTHON_CMD" == "python" ]; then
    PYTHON3_CMD="python"
else
    PYTHON3_CMD="python3"
fi

# Get script directory (where MCP package is)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(pwd)"

# If running from within mcp-agentic-rules, install to parent
if [[ "$SCRIPT_DIR" == *"mcp-agentic-rules"* ]]; then
    MCP_SOURCE="$SCRIPT_DIR"
else
    MCP_SOURCE="$SCRIPT_DIR/mcp-agentic-rules"
fi

# Target installation path
MCP_TARGET="$PROJECT_ROOT/mcp-agentic-rules"

# ============================================================================
# STEP 1: Copy MCP package
# ============================================================================
info "Step 1/6: Installing MCP package..."

if [ "$MCP_SOURCE" != "$MCP_TARGET" ]; then
    if [ -d "$MCP_TARGET" ]; then
        warn "MCP already exists. Updating..."
        rm -rf "$MCP_TARGET"
    fi
    
    cp -r "$MCP_SOURCE" "$MCP_TARGET"
    ok "Copied MCP to $MCP_TARGET"
else
    ok "MCP already in place"
fi

# ============================================================================
# STEP 2: Install git hooks
# ============================================================================
info "Step 2/6: Installing git hooks..."

if [ -d ".git" ]; then
    HOOKS_SOURCE="$MCP_TARGET/.git-hooks"
    HOOKS_TARGET=".git/hooks"
    
    mkdir -p "$HOOKS_TARGET"
    
    for hook in pre-commit post-commit commit-msg pre-push post-checkout post-merge; do
        if [ -f "$HOOKS_SOURCE/$hook" ]; then
            cp "$HOOKS_SOURCE/$hook" "$HOOKS_TARGET/$hook"
            chmod +x "$HOOKS_TARGET/$hook"
        fi
    done
    
    ok "Installed 6 git hooks"
else
    warn "Skipping hooks (not a git repo)"
fi

# ============================================================================
# STEP 3: Create .mcp directory
# ============================================================================
info "Step 3/6: Creating MCP data directory..."

mkdir -p ".mcp"
ok "Created .mcp/"

# ============================================================================
# STEP 4: Build initial indexes
# ============================================================================
info "Step 4/6: Building indexes..."

cd "$MCP_TARGET"
$PYTHON_CMD mcp.py index-all --quick 2>/dev/null &
INDEX_PID=$!
ok "Index build started (background)"

# ============================================================================
# STEP 5: Create AI agent instructions
# ============================================================================
info "Step 5/6: Creating AI agent instructions..."

cat > "$PROJECT_ROOT/AI_AGENT_MCP.md" << 'EOF'
# MCP Global Rules - AI Agent Instructions

## Available Commands (50 total)

Run with: `${PYTHON3_CMD} mcp-agentic-rules/mcp.py <command>`

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

### Project Packs
```bash
mcp pack list                # List available project packs
mcp pack install <pack_name> # Setup virtual environment and install pack
```

### Remember & Learn
```bash
mcp remember "key" "value"   # Store knowledge
mcp recall "query"           # Search knowledge
mcp learn --patterns         # View learned patterns
```

## Hooks (Automatic)

All hooks are installed and will run automatically:
- **pre-commit**: Auto-fix, risk check, security scan, review
- **post-commit**: Learning, index update
- **post-checkout**: Warm indexes

## Key Directories

- `mcp-agentic-rules/` - MCP package
- `.mcp/` - Index data (auto-generated)

## Quick Reference

| Need | Command |
|------|---------|
| Context | `mcp autocontext` |
| Search | `mcp search "query"` |
| Review | `mcp review .` |
| Bugs | `mcp predict-bugs .` |
| Tests | `mcp test-gen file.py` |
| Memory | `mcp remember/recall` |
EOF

ok "Created AI_AGENT_MCP.md"

# Make the install discoverable to AI agents with zero manual wiring:
# CLAUDE.md section (Claude Code), AGENTS.md section (Cursor/Codex/etc.),
# and .mcp.json registration of the native MCP server.
"$PYTHON_CMD" "$MCP_TARGET/mcp.py" integrate
ok "Agent discovery wired (CLAUDE.md, AGENTS.md, .mcp.json)"

# ============================================================================
# STEP 6: Install Project Pack
# ============================================================================
info "Step 6/6: Configuring Project Pack..."

PACKS_DIR="$PROJECT_ROOT/project_packs"
AVAILABLE_PACKS=()

if [ -d "$PACKS_DIR" ]; then
    for d in "$PACKS_DIR"/*; do
        if [ -d "$d" ]; then
            AVAILABLE_PACKS+=("$(basename "$d")")
        fi
    done
fi

contains_element() {
    local e match="$1"
    shift
    for e; do [[ "$e" == "$match" ]] && return 0; done
    return 1
}

if [ -z "$PACK" ] && [ ${#AVAILABLE_PACKS[@]} -gt 0 ]; then
    # Check if interactive
    if [ -t 0 ] && [ -t 1 ]; then
        echo ""
        echo -e "${CYAN}Available Project Packs:${NC}"
        for i in "${!AVAILABLE_PACKS[@]}"; do
            echo -e "  [$((i+1))] ${AVAILABLE_PACKS[$i]}"
        done
        echo "  [N] None (Skip project pack installation)"
        echo ""
        
        # Auto-detect default project pack
        DETECTED_PACK=""
        if [ -f "package.json" ] || [ -f "tsconfig.json" ] || find . -maxdepth 2 \( -name "*.js" -o -name "*.ts" \) 2>/dev/null | grep -q .; then
            DETECTED_PACK="Fullstack_Web_Development"
        elif find . -maxdepth 2 -name "*.ipynb" 2>/dev/null | grep -q . || ( [ -f "requirements.txt" ] && grep -Eiq "torch|tensorflow|numpy|pandas|scikit-learn" requirements.txt 2>/dev/null ); then
            DETECTED_PACK="AI_Machine_Learning_CUDA"
        fi

        DEFAULT_TEXT="None"
        if [ -n "$DETECTED_PACK" ]; then
            DEFAULT_TEXT="$DETECTED_PACK"
        fi

        read -p "Select a project pack to install [$DEFAULT_TEXT]: " SELECTION
        if [ -z "$SELECTION" ] && [ -n "$DETECTED_PACK" ]; then
            PACK="$DETECTED_PACK"
        elif [[ "$SELECTION" == "N" || "$SELECTION" == "n" || "$SELECTION" == "None" ]]; then
            PACK=""
        elif [[ "$SELECTION" =~ ^[0-9]+$ ]]; then
            INDEX=$((SELECTION-1))
            if [ "$INDEX" -ge 0 ] && [ "$INDEX" -lt "${#AVAILABLE_PACKS[@]}" ]; then
                PACK="${AVAILABLE_PACKS[$INDEX]}"
            fi
        fi
    fi
fi

if [ -n "$PACK" ]; then
    if contains_element "$PACK" "${AVAILABLE_PACKS[@]}"; then
        info "Installing project pack '$PACK'..."
        $PYTHON_CMD "$MCP_TARGET/mcp.py" pack install "$PACK"
    else
        warn "Project pack '$PACK' is not available. Skipping pack installation."
    fi
else
    info "No project pack selected. Skipping pack installation."
fi

# ============================================================================
# DONE
# ============================================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          MCP INSTALLATION COMPLETE!                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Installed:
  ✓ 42 Python scripts
  ✓ 50 CLI commands
  ✓ 6 git hooks (enforced)
  ✓ AI agent instructions"
echo ""
echo "Usage:"
echo "  ${PYTHON3_CMD} mcp-agentic-rules/mcp.py help"
echo "  ${PYTHON3_CMD} mcp-agentic-rules/mcp.py <command>"
echo ""
echo "Quick start:"
echo "  ${PYTHON3_CMD} mcp-agentic-rules/mcp.py autocontext"
echo "  ${PYTHON3_CMD} mcp-agentic-rules/mcp.py search \"your query\""
echo ""

exit 0
