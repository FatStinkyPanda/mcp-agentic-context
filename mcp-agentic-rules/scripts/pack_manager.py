"""
MCP Project Pack Manager
=========================
Manages modular project packs (e.g., AI_Machine_Learning_CUDA, Fullstack_Web_Development).

Usage:
    python mcp.py pack list
    python mcp.py pack install <pack_name>
"""

from pathlib import Path
import os
import sys
import subprocess
from .utils import Console, find_project_root
from .venv_manager import VenvManager


def get_packs_dir() -> Path:
    """Get the path to the project_packs directory."""
    project_root = find_project_root() or Path.cwd()
    return project_root / "project_packs"


def list_packs() -> int:
    """List all available project packs."""
    packs_dir = get_packs_dir()
    
    if not packs_dir.exists():
        Console.fail(f"Project packs directory not found at: {packs_dir}")
        return 1
        
    Console.header("Available Project Packs")
    
    found_packs = False
    for item in packs_dir.iterdir():
        if item.is_dir():
            found_packs = True
            req_file = item / "requirements.txt"
            has_reqs = "Yes" if req_file.exists() else "No"
            
            # Check for installers
            has_ps1 = (item / "install.ps1").exists()
            has_sh = (item / "install.sh").exists()
            installers = []
            if has_ps1: installers.append("install.ps1")
            if has_sh: installers.append("install.sh")
            installers_str = ", ".join(installers) if installers else "None"
            
            Console.info(f"- {Console._color(item.name, 'bold')}")
            print(f"  Requirements: {has_reqs}")
            print(f"  Installers:   {installers_str}")
            print("")
            
    if not found_packs:
        Console.warn("No project packs found in project_packs/ directory.")
        
    return 0


def install_pack(pack_name: str) -> int:
    """Install the specified project pack."""
    project_root = find_project_root() or Path.cwd()
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if not pack_path.exists() or not pack_path.is_dir():
        Console.fail(f"Project pack '{pack_name}' not found at: {pack_path}")
        list_packs()
        return 1
        
    Console.header(f"Installing Project Pack: {pack_name}")
    
    # 1. Ensure venv exists
    Console.info("Ensuring virtual environment is ready...")
    venv_mgr = VenvManager(str(project_root))
    if not venv_mgr.ensure_venv():
        Console.fail("Failed to set up virtual environment.")
        return 1
        
    # 2. Run pack installer script if present
    is_windows = sys.platform == "win32"
    ps1_installer = pack_path / "install.ps1"
    sh_installer = pack_path / "install.sh"
    
    if is_windows and ps1_installer.exists():
        Console.info(f"Running PowerShell installer: {ps1_installer.name}")
        try:
            # Run PowerShell script
            result = subprocess.run(
                ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(ps1_installer)],
                cwd=str(project_root),
                check=True
            )
            Console.ok(f"Successfully ran installer for {pack_name}.")
            return 0
        except subprocess.CalledProcessError as e:
            Console.fail(f"Installer script failed: {e}")
            return 1
    elif not is_windows and sh_installer.exists():
        Console.info(f"Running Bash installer: {sh_installer.name}")
        try:
            # Make sure script is executable
            os.chmod(sh_installer, 0o755)
            result = subprocess.run(
                ["bash", str(sh_installer)],
                cwd=str(project_root),
                check=True
            )
            Console.ok(f"Successfully ran installer for {pack_name}.")
            return 0
        except subprocess.CalledProcessError as e:
            Console.fail(f"Installer script failed: {e}")
            return 1
            
    # 3. Fallback: pip install requirements.txt inside venv
    req_file = pack_path / "requirements.txt"
    if req_file.exists():
        Console.info(f"No specific platform installer found. Installing dependencies via pip...")
        try:
            # Reuse _run_in_venv if possible, or build command
            python_exe = venv_mgr.get_venv_python()
            subprocess.run(
                [python_exe, "-m", "pip", "install", "-r", str(req_file)],
                cwd=str(project_root),
                check=True
            )
            Console.ok(f"Successfully installed requirements for {pack_name}.")
            return 0
        except subprocess.CalledProcessError as e:
            Console.fail(f"Pip installation failed: {e}")
            return 1
            
    Console.fail(f"No requirements.txt or installer scripts found in {pack_name}.")
    return 1


def create_pack(pack_name: str, required_python: str = "3.11", description: str = "") -> bool:
    """Create a new custom project pack dynamically."""
    import json
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if pack_path.exists():
        Console.fail(f"Project pack '{pack_name}' already exists.")
        return False
        
    try:
        pack_path.mkdir(parents=True, exist_ok=True)
        
        # 1. Write pack.json
        metadata = {
            "name": pack_name,
            "required_python": required_python,
            "description": description
        }
        with open(pack_path / "pack.json", "w") as f:
            json.dump(metadata, f, indent=2)
            
        # 2. Write empty requirements.txt
        with open(pack_path / "requirements.txt", "w") as f:
            f.write("# Package requirements for " + pack_name + "\n")
            
        # 3. Create wheels/ folder
        (pack_path / "wheels").mkdir(exist_ok=True)
        
        # 4. Generate install.ps1
        ps1_tpl = f"""# Usage: .\\install.ps1
# Auto-generated installer for {pack_name}
$root = $PSScriptRoot
$reqFile = Join-Path $root "requirements.txt"
$wheelsDir = Join-Path $root "wheels"
$venvPath = Join-Path (Get-Location) ".venv"

if (-not (Test-Path $venvPath)) {{
    Write-Host "Creating .venv with Python..."
    python -m venv $venvPath
}}

Write-Host "Activating .venv and installing dependencies..."
& "$venvPath\\Scripts\\Activate.ps1"
python -m pip install --upgrade pip

if (Test-Path $wheelsDir) {{
    pip install --no-index --find-links $wheelsDir -r $reqFile
}} else {{
    pip install -r $reqFile
}}
Write-Host "Setup complete!"
"""
        with open(pack_path / "install.ps1", "w") as f:
            f.write(ps1_tpl)
            
        # 5. Generate install.sh
        sh_tpl = f"""#!/bin/bash
# Auto-generated installer for {pack_name}
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
WHEELS_DIR="$SCRIPT_DIR/wheels"
VENV_PATH="./.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating .venv..."
    python3 -m venv "$VENV_PATH"
fi

echo "Activating .venv..."
source "$VENV_PATH/bin/activate"
python3 -m pip install --upgrade pip

if [ -d "$WHEELS_DIR" ]; then
    pip install --no-index --find-links "$WHEELS_DIR" -r "$REQ_FILE"
else
    pip install -r "$REQ_FILE"
fi
echo "Setup complete!"
"""
        with open(pack_path / "install.sh", "w") as f:
            f.write(sh_tpl)
        os.chmod(pack_path / "install.sh", 0o755)
        
        Console.ok(f"Successfully created project pack '{pack_name}' at {pack_path}.")
        return True
    except Exception as e:
        Console.fail(f"Failed to create project pack '{pack_name}': {e}")
        return False


def delete_pack(pack_name: str) -> bool:
    """Delete a project pack folder."""
    import shutil
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if not pack_path.exists() or not pack_path.is_dir():
        Console.fail(f"Project pack '{pack_name}' not found.")
        return False
        
    try:
        shutil.rmtree(pack_path)
        Console.ok(f"Successfully deleted project pack '{pack_name}'.")
        return True
    except Exception as e:
        Console.fail(f"Failed to delete project pack '{pack_name}': {e}")
        return False


def add_package_to_pack(pack_name: str, package_name: str) -> bool:
    """Add a package to a pack's requirements and download its offline wheel."""
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if not pack_path.exists() or not pack_path.is_dir():
        Console.fail(f"Project pack '{pack_name}' not found.")
        return False
        
    req_file = pack_path / "requirements.txt"
    wheels_dir = pack_path / "wheels"
    wheels_dir.mkdir(exist_ok=True)
    
    # 1. Update requirements.txt if not present
    lines = []
    if req_file.exists():
        with open(req_file, "r") as f:
            lines = [line.strip() for line in f.readlines()]
            
    clean_package = package_name.strip()
    if clean_package.lower() in [l.lower() for l in lines if l and not l.startswith("#")]:
        Console.info(f"Package '{clean_package}' already listed in requirements.txt.")
    else:
        with open(req_file, "a") as f:
            f.write(f"\n{clean_package}")
        Console.ok(f"Added package '{clean_package}' to requirements.txt.")

    # 2. Download offline wheel using current python pip
    Console.info(f"Downloading offline wheel for '{clean_package}'...")
    try:
        # Use sys.executable to run pip download
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "-d", str(wheels_dir), clean_package],
            check=True
        )
        Console.ok(f"Successfully downloaded offline wheel for '{clean_package}' to wheels/.")
        return True
    except subprocess.CalledProcessError as e:
        Console.fail(f"Failed to download wheel for '{clean_package}': {e}")
        # Revert requirements.txt change
        if req_file.exists():
            with open(req_file, "r") as f:
                content = f.read()
            # Remove just the appended line
            content = content.replace(f"\n{clean_package}", "")
            with open(req_file, "w") as f:
                f.write(content)
        return False


def remove_package_from_pack(pack_name: str, package_name: str) -> bool:
    """Remove a package from a pack's requirements and delete its wheels."""
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if not pack_path.exists() or not pack_path.is_dir():
        Console.fail(f"Project pack '{pack_name}' not found.")
        return False
        
    req_file = pack_path / "requirements.txt"
    wheels_dir = pack_path / "wheels"
    
    # 1. Update requirements.txt
    if req_file.exists():
        with open(req_file, "r") as f:
            lines = f.readlines()
        new_lines = []
        removed = False
        for line in lines:
            if line.strip().lower() == package_name.strip().lower():
                removed = True
                continue
            new_lines.append(line)
        
        if removed:
            with open(req_file, "w") as f:
                f.writelines(new_lines)
            Console.ok(f"Removed package '{package_name}' from requirements.txt.")
        else:
            Console.warn(f"Package '{package_name}' not found in requirements.txt.")
            
    # 2. Delete downloaded wheels matching this package name
    if wheels_dir.exists():
        safe_pkg = package_name.strip().replace("-", "_").lower()
        deleted_count = 0
        for whl in wheels_dir.glob("*.whl"):
            if whl.name.lower().startswith(safe_pkg):
                try:
                    whl.unlink()
                    deleted_count += 1
                except Exception as e:
                    Console.warn(f"Could not delete wheel file '{whl.name}': {e}")
        if deleted_count > 0:
            Console.ok(f"Purged {deleted_count} matching offline wheel files.")
            
    return True


def normalize_package_name(req_str: str) -> str:
    """Extract and normalize the core package name from a requirement string."""
    req = req_str.split('#')[0].strip()
    if not req:
        return ""
    for op in ['==', '>=', '<=', '>', '<', '!=', '~=']:
        if op in req:
            req = req.split(op)[0].strip()
    if '[' in req:
        req = req.split('[')[0].strip()
    return req.replace('-', '_').lower()


def is_package_cached(pack_name: str, package_req: str) -> bool:
    """Check if a package requirement has a matching downloaded wheel file."""
    packs_dir = get_packs_dir()
    wheels_dir = packs_dir / pack_name / "wheels"
    if not wheels_dir.exists():
        return False
        
    norm_name = normalize_package_name(package_req)
    if not norm_name:
        return False
        
    prefix = f"{norm_name}_"
    for whl in wheels_dir.glob("*"):
        w_name = whl.name.lower().replace('-', '_')
        if w_name.startswith(prefix) or w_name == norm_name or w_name.startswith(norm_name + "."):
            return True
            
    return False


def get_pack_package_status(pack_name: str) -> list:
    """Get list of package requirements for a pack with their cached status."""
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    req_file = pack_path / "requirements.txt"
    
    if not req_file.exists():
        return []
        
    try:
        with open(req_file, "r") as f:
            lines = f.readlines()
    except Exception:
        return []
        
    status_list = []
    for line in lines:
        line_strip = line.strip()
        if not line_strip or line_strip.startswith('#'):
            continue
            
        cached = is_package_cached(pack_name, line_strip)
        status_list.append({
            "requirement": line_strip,
            "cached": cached
        })
        
    return status_list


def download_pack_wheels(pack_name: str) -> bool:
    """Download offline wheels for all requirements in the pack."""
    packs_dir = get_packs_dir()
    pack_path = packs_dir / pack_name
    
    if not pack_path.exists() or not pack_path.is_dir():
        Console.fail(f"Project pack '{pack_name}' not found.")
        return False
        
    req_file = pack_path / "requirements.txt"
    if not req_file.exists():
        Console.warn(f"No requirements.txt found for pack '{pack_name}'.")
        return True
        
    wheels_dir = pack_path / "wheels"
    wheels_dir.mkdir(exist_ok=True)
    
    Console.info(f"Downloading offline wheels for pack '{pack_name}' to {wheels_dir}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "-d", str(wheels_dir), "-r", str(req_file)],
            check=True
        )
        Console.ok(f"Successfully downloaded all offline wheels for '{pack_name}'.")
        return True
    except subprocess.CalledProcessError as e:
        Console.fail(f"Failed to download wheels for '{pack_name}': {e}")
        return False


def main() -> int:
    """CLI entry point for pack command."""
    if len(sys.argv) < 2:
        Console.info("Usage:")
        Console.info("  mcp pack list                          List available packs")
        Console.info("  mcp pack install <pack_name>           Install a project pack")
        Console.info("  mcp pack create <name> [py_ver] [desc] Create a new project pack")
        Console.info("  mcp pack delete <name>                 Delete a project pack")
        Console.info("  mcp pack add-pkg <pack> <package>      Add package & download wheel")
        Console.info("  mcp pack remove-pkg <pack> <package>   Remove package & wheels")
        Console.info("  mcp pack download-wheels <pack_name>   Download all wheels for requirements")
        return 0
        
    cmd = sys.argv[1]
    
    if cmd == "list":
        return list_packs()
    elif cmd == "install":
        if len(sys.argv) < 3:
            Console.fail("Please specify a pack name to install.")
            return 1
        pack_name = sys.argv[2]
        return install_pack(pack_name)
    elif cmd == "create":
        if len(sys.argv) < 3:
            Console.fail("Please specify a pack name to create.")
            return 1
        name = sys.argv[2]
        py_ver = sys.argv[3] if len(sys.argv) > 3 else "3.11"
        desc = sys.argv[4] if len(sys.argv) > 4 else ""
        return 0 if create_pack(name, py_ver, desc) else 1
    elif cmd == "delete":
        if len(sys.argv) < 3:
            Console.fail("Please specify a pack name to delete.")
            return 1
        return 0 if delete_pack(sys.argv[2]) else 1
    elif cmd == "add-pkg":
        if len(sys.argv) < 4:
            Console.fail("Usage: mcp pack add-pkg <pack_name> <package_name>")
            return 1
        return 0 if add_package_to_pack(sys.argv[2], sys.argv[3]) else 1
    elif cmd == "remove-pkg":
        if len(sys.argv) < 4:
            Console.fail("Usage: mcp pack remove-pkg <pack_name> <package_name>")
            return 1
        return 0 if remove_package_from_pack(sys.argv[2], sys.argv[3]) else 1
    elif cmd == "download-wheels":
        if len(sys.argv) < 3:
            Console.fail("Please specify a pack name to download wheels.")
            return 1
        return 0 if download_pack_wheels(sys.argv[2]) else 1
    else:
        Console.fail(f"Unknown pack command: {cmd}")
        return 1

