#!/usr/bin/env python3
"""
Setup script to create a virtual environment and install dependencies.
This is used in production to ensure Python packages are available.
"""
import sys
import os
import subprocess
import venv
from pathlib import Path

def setup_venv(venv_path, requirements_path):
    """Create virtual environment and install requirements."""
    venv_path = Path(venv_path)
    requirements_path = Path(requirements_path)
    
    print(f"Setting up virtual environment at: {venv_path}")
    
    # Create virtual environment if it doesn't exist
    if not venv_path.exists():
        print("Creating virtual environment...")
        venv.create(venv_path, with_pip=True)
        print("Virtual environment created successfully.")
    else:
        print("Virtual environment already exists.")
    
    # Determine Python executable in venv
    if sys.platform == 'win32':
        python_exe = venv_path / 'Scripts' / 'python.exe'
        pip_exe = venv_path / 'Scripts' / 'pip.exe'
    else:
        python_exe = venv_path / 'bin' / 'python'
        pip_exe = venv_path / 'bin' / 'pip'
    
    # Upgrade pip and install build tools
    print("Upgrading pip and installing build tools...")
    try:
        subprocess.check_call([
            str(pip_exe), 'install', '--upgrade', 'pip', 'wheel', 'setuptools'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120000)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Warning: Failed to upgrade pip: {e}")
    
    # Install requirements - install critical packages first, then optional ones
    if requirements_path.exists():
        print(f"Installing requirements from: {requirements_path}")
        
        # Critical packages needed for the app to run
        critical_packages = [
            'fastapi==0.109.0',
            'uvicorn[standard]==0.27.0',
            'sqlalchemy>=2.0.25',
            'pydantic>=2.6.0',
            'pydantic-settings==2.1.0',
            'python-jose[cryptography]==3.3.0',
            'passlib[bcrypt]==1.7.4',
            'python-multipart==0.0.6',
            'python-dotenv==1.0.0',
            'email-validator==2.1.0',
            'alembic>=1.13.0',
        ]
        
        print("Installing critical packages...")
        failed_critical = []
        for package in critical_packages:
            try:
                subprocess.check_call([
                    str(pip_exe), 'install', package,
                    '--prefer-binary',  # Prefer pre-built wheels (no compilation)
                    '--no-cache-dir',
                ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120000)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"Error: Failed to install critical package {package}: {e}")
                failed_critical.append(package)
        
        if failed_critical:
            print(f"Error: Critical packages failed to install: {failed_critical}")
            sys.exit(1)
        
        # Optional packages (image processing, QR codes, reports)
        # These can fail without breaking the app
        optional_packages = [
            'reportlab==4.0.7',
            'qrcode==7.4.2',
            'Pillow==10.4.0',  # May fail if build tools unavailable
        ]
        
        print("Installing optional packages...")
        for package in optional_packages:
            try:
                subprocess.check_call([
                    str(pip_exe), 'install', package,
                    '--prefer-binary',
                    '--no-cache-dir',
                ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120000)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"Warning: Optional package {package} failed to install: {e}")
                print("App will continue without this package.")
        
        # Verify critical packages are installed
        print("Verifying installation...")
        missing = []
        import_map = {
            'uvicorn': 'uvicorn',
            'fastapi': 'fastapi',
            'pydantic': 'pydantic',
            'pydantic-settings': 'pydantic_settings',
            'sqlalchemy': 'sqlalchemy',
        }
        
        for pkg_name, import_name in import_map.items():
            try:
                subprocess.check_call([
                    str(python_exe), '-c', f'import {import_name}'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5000)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                missing.append(pkg_name)
        
        if missing:
            print(f"Error: Critical packages missing: {missing}")
            sys.exit(1)
        
        print("Requirements installed successfully.")
        return str(python_exe)
    else:
        print(f"Warning: Requirements file not found: {requirements_path}")
        return str(python_exe)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Setup Python virtual environment')
    parser.add_argument('venv_path', help='Path to virtual environment')
    parser.add_argument('requirements_path', help='Path to requirements.txt')
    args = parser.parse_args()
    
    python_exe = setup_venv(args.venv_path, args.requirements_path)
    print(f"Python executable: {python_exe}")
