# ============================================================================
# MCP Global Rules - Single Command Install (PowerShell)
# ============================================================================
# Usage: .\install.ps1
#        irm https://example.com/mcp/install.ps1 | iex
#
# This installs MCP to the current project with:
#   - All 42 Python scripts
#   - All 6 git hooks (auto-installed)
#   - Full indexing
#   - AI agent instructions
# ============================================================================

param(
    [switch]$SkipHooks,
    [switch]$SkipIndex,
    [string]$Pack
)

$ErrorActionPreference = "Stop"

function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Write-Ok { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|          MCP GLOBAL RULES INSTALLER                  |" -ForegroundColor Cyan
Write-Host "|          42 Scripts | 50 Commands | 6 Hooks          |" -ForegroundColor Cyan
Write-Host "+------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# Check if in a git repository
$IsGitRepo = Test-Path ".git"
if (-not $IsGitRepo) {
    Write-Warn "Not a git repository. Some features will be limited."
}

# Detect Python
$PythonCmd = $null
if (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $PythonCmd = "python3"
}
elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
}
else {
    Write-Fail "Python not found. Please install Python 3.8+"
}

$PythonVersion = & $PythonCmd --version 2>&1
Write-Info "Python: $PythonCmd ($PythonVersion)"

# Paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Get-Location

# Determine MCP source
if ($ScriptDir -like "*mcp-agentic-rules*") {
    $MCPSource = $ScriptDir
}
else {
    $MCPSource = Join-Path $ScriptDir "mcp-agentic-rules"
}

$MCPTarget = Join-Path $ProjectRoot "mcp-agentic-rules"

# ============================================================================
# STEP 1: Copy MCP package
# ============================================================================
Write-Info "Step 1/6: Installing MCP package..."

if ($MCPSource -ne $MCPTarget) {
    if (Test-Path $MCPTarget) {
        Write-Warn "MCP already exists. Updating..."
        Remove-Item -Recurse -Force $MCPTarget
    }
    
    Copy-Item -Recurse $MCPSource $MCPTarget
    Write-Ok "Copied MCP to $MCPTarget"
}
else {
    Write-Ok "MCP already in place"
}

# ============================================================================
# STEP 2: Install git hooks
# ============================================================================
Write-Info "Step 2/6: Installing git hooks..."

if ($IsGitRepo -and -not $SkipHooks) {
    $HooksSource = Join-Path $MCPTarget ".git-hooks"
    $HooksTarget = Join-Path $ProjectRoot ".git\hooks"
    
    if (-not (Test-Path $HooksTarget)) {
        New-Item -ItemType Directory -Path $HooksTarget -Force | Out-Null
    }
    
    $Hooks = @("pre-commit", "post-commit", "commit-msg", "pre-push", "post-checkout", "post-merge")
    $InstalledCount = 0
    
    foreach ($hook in $Hooks) {
        $SourceHook = Join-Path $HooksSource $hook
        $TargetHook = Join-Path $HooksTarget $hook
        
        if (Test-Path $SourceHook) {
            Copy-Item $SourceHook $TargetHook -Force
            $InstalledCount++
        }
    }
    
    Write-Ok "Installed $InstalledCount git hooks"
}
else {
    Write-Warn "Skipping hooks"
}

# ============================================================================
# STEP 3: Create .mcp directory
# ============================================================================
Write-Info "Step 3/6: Creating MCP data directory..."

$MCPData = Join-Path $ProjectRoot ".mcp"
if (-not (Test-Path $MCPData)) {
    New-Item -ItemType Directory -Path $MCPData -Force | Out-Null
}
Write-Ok "Created .mcp/"

# ============================================================================
# STEP 4: Build initial indexes
# ============================================================================
Write-Info "Step 4/6: Building indexes..."

if (-not $SkipIndex) {
    Push-Location $MCPTarget
    Start-Job -ScriptBlock {
        param($python, $mcp)
        Set-Location $mcp
        & $python mcp.py index-all --quick 2>$null
    } -ArgumentList $PythonCmd, $MCPTarget | Out-Null
    Pop-Location
    Write-Ok "Index build started (background)"
}
else {
    Write-Warn "Skipping index build"
}

# ============================================================================
# STEP 5: Create AI agent instructions
# ============================================================================
Write-Info "Step 5/6: Creating AI agent instructions..."

$AIInstructions = @"
# MCP Global Rules - AI Agent Instructions

## Available Commands (50 total)

Run with: ``$PythonCmd mcp-agentic-rules/mcp.py <command>``

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

- ``mcp-agentic-rules/`` - MCP package
- ``.mcp/`` - Index data (auto-generated)

## Quick Reference

| Need | Command |
|------|---------|
| Context | ``mcp autocontext`` |
| Search | ``mcp search "query"`` |
| Review | ``mcp review .`` |
| Bugs | ``mcp predict-bugs .`` |
| Tests | ``mcp test-gen file.py`` |
| Memory | ``mcp remember/recall`` |
"@

$AIInstructions | Out-File -FilePath (Join-Path $ProjectRoot "AI_AGENT_MCP.md") -Encoding UTF8
Write-Ok "Created AI_AGENT_MCP.md"

# Make the install discoverable to AI agents with zero manual wiring:
# CLAUDE.md section (Claude Code), AGENTS.md section (Cursor/Codex/etc.),
# and .mcp.json registration of the native MCP server.
& $PythonCmd (Join-Path $MCPTarget "mcp.py") integrate
Write-Ok "Agent discovery wired (CLAUDE.md, AGENTS.md, .mcp.json)"

# ============================================================================
# STEP 6: Install Project Pack
# ============================================================================
Write-Info "Step 6/6: Configuring Project Pack..."

$PacksDir = Join-Path $ProjectRoot "project_packs"
$AvailablePacks = @()
if (Test-Path $PacksDir) {
    $AvailablePacks = Get-ChildItem $PacksDir | Where-Object { $_.PSIsContainer } | Select-Object -ExpandProperty Name
}

if (-not $Pack -and $AvailablePacks.Count -gt 0) {
    # Check if session is interactive
    if ([Environment]::UserInteractive) {
        Write-Host ""
        Write-Host "Available Project Packs:" -ForegroundColor Cyan
        for ($i = 0; $i -lt $AvailablePacks.Count; $i++) {
            Write-Host "  [$($i + 1)] $($AvailablePacks[$i])"
        }
        Write-Host "  [N] None (Skip project pack installation)"
        Write-Host ""
        
        # Auto-detect default project pack
        $DetectedPack = $null
        if (Test-Path "package.json" -Or Test-Path "tsconfig.json" -Or (Get-ChildItem -Filter "*.js" -Recurse -Depth 2 -ErrorAction SilentlyContinue) -Or (Get-ChildItem -Filter "*.ts" -Recurse -Depth 2 -ErrorAction SilentlyContinue)) {
            $DetectedPack = "Fullstack_Web_Development"
        } elseif ((Get-ChildItem -Filter "*.ipynb" -Recurse -Depth 2 -ErrorAction SilentlyContinue) -Or (Test-Path "requirements.txt" -And (Select-String -Path "requirements.txt" -Pattern "torch|tensorflow|numpy|pandas|scikit-learn" -ErrorAction SilentlyContinue))) {
            $DetectedPack = "AI_Machine_Learning_CUDA"
        }

        $DefaultText = "None"
        if ($DetectedPack) {
            $DefaultText = $DetectedPack
        }
        
        $Selection = Read-Host "Select a project pack to install [$DefaultText]"
        if ($Selection -eq "") {
            $Pack = $DetectedPack
        } elseif ($Selection -eq "N" -Or $Selection -eq "n" -Or $Selection -eq "None") {
            $Pack = $null
        } elseif ($Selection -match '^\d+$') {
            $Index = [int]$Selection - 1
            if ($Index -ge 0 -and $Index -lt $AvailablePacks.Count) {
                $Pack = $AvailablePacks[$Index]
            }
        }
    }
}

if ($Pack) {
    if ($AvailablePacks -contains $Pack) {
        Write-Info "Installing project pack '$Pack'..."
        & $PythonCmd mcp-agentic-rules/mcp.py pack install $Pack
    } else {
        Write-Warn "Project pack '$Pack' is not available. Skipping pack installation."
    }
} else {
    Write-Info "No project pack selected. Skipping pack installation."
}

# ============================================================================
# DONE
# ============================================================================
Write-Host ""
Write-Host "+------------------------------------------------------+" -ForegroundColor Green
Write-Host "|          MCP INSTALLATION COMPLETE!                  |" -ForegroundColor Green
Write-Host "+------------------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "Installed:"
Write-Host "  - 42 Python scripts"
Write-Host "  - 50 CLI commands"
Write-Host "  - 6 git hooks (enforced)"
Write-Host "  - AI agent instructions"
Write-Host ""
Write-Host "Usage:"
Write-Host "  $PythonCmd mcp-agentic-rules/mcp.py help"
Write-Host "  $PythonCmd mcp-agentic-rules/mcp.py <command>"
Write-Host ""
Write-Host "Quick start:"
Write-Host "  $PythonCmd mcp-agentic-rules/mcp.py autocontext"
Write-Host "  $PythonCmd mcp-agentic-rules/mcp.py search `"your query`""
Write-Host ""
