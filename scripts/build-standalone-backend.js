#!/usr/bin/env node
/**
 * Build script to create a pre-bundled Python virtual environment
 * This ensures the app is self-contained with all Python dependencies pre-installed
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PLATFORM = process.platform;
const ARCH = process.arch;
const BACKEND_DIR = path.join(__dirname, '..', 'backend');
const BUILD_DIR = path.join(__dirname, '..', 'build');
const BUNDLED_VENV_DIR = path.join(BUILD_DIR, 'bundled-venv');

function log(message) {
  console.log(`[Backend Build] ${message}`);
}

function error(message) {
  console.error(`[Backend Build ERROR] ${message}`);
  process.exit(1);
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * Replace symlinks inside dir with copies of their targets (files only).
 * Required for macOS code signing: symlinks in the app bundle can cause
 * "invalid destination for symbolic link in bundle" during codesign --verify.
 */
function resolveSymlinksInDir(dir) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isSymbolicLink()) {
      let target;
      try {
        target = fs.realpathSync(full);
      } catch (_) {
        continue;
      }
      if (!target.startsWith(BUNDLED_VENV_DIR)) continue;
      const stat = fs.statSync(target);
      if (stat.isFile()) {
        fs.unlinkSync(full);
        fs.copyFileSync(target, full);
        fs.chmodSync(full, stat.mode);
      }
      // Directory symlinks (e.g. Versions/Current) are left as-is; they often
      // point inside the same tree and may still break codesign - we'll resolve those too
    } else if (ent.isDirectory()) {
      resolveSymlinksInDir(full);
    }
  }
}

async function buildBundledVenv() {
  log('Building bundled Python virtual environment...');
  log(`Platform: ${PLATFORM}, Arch: ${ARCH}`);
  
  ensureDir(BUILD_DIR);
  
  // Remove old bundled venv if it exists
  if (fs.existsSync(BUNDLED_VENV_DIR)) {
    log('Removing old bundled venv...');
    fs.rmSync(BUNDLED_VENV_DIR, { recursive: true, force: true });
  }
  
  // Check if Python is available
  const pythonCmd = PLATFORM === 'win32' ? 'python' : 'python3';
  let pythonPath;
  
  try {
    pythonPath = execSync(`which ${pythonCmd}`, { encoding: 'utf8' }).trim();
    const pythonVersion = execSync(`${pythonCmd} --version`, { encoding: 'utf8' }).trim();
    log(`Found Python: ${pythonPath} (${pythonVersion})`);
  } catch (err) {
    error(`Python not found. Please install Python 3.9+ first.`);
  }
  
  const requirementsPath = path.join(BACKEND_DIR, 'requirements.txt');
  
  if (!fs.existsSync(requirementsPath)) {
    error(`Requirements file not found: ${requirementsPath}`);
  }
  
  // Create venv
  log('Creating virtual environment...');
  try {
    execSync(`${pythonCmd} -m venv "${BUNDLED_VENV_DIR}"`, {
      stdio: 'inherit',
      timeout: 120000,
    });
  } catch (err) {
    error(`Failed to create venv: ${err.message}`);
  }
  
  // Install dependencies
  const pipCmd = PLATFORM === 'win32'
    ? path.join(BUNDLED_VENV_DIR, 'Scripts', 'pip.exe')
    : path.join(BUNDLED_VENV_DIR, 'bin', 'pip');
  
  log('Upgrading pip...');
  try {
    execSync(`"${pipCmd}" install --upgrade pip wheel setuptools`, {
      stdio: 'inherit',
      timeout: 120000,
    });
  } catch (err) {
    error(`Failed to upgrade pip: ${err.message}`);
  }

  // Install Pillow first using only pre-built wheels (avoids build failures on macOS/ARM)
  log('Installing Pillow from binary wheel...');
  try {
    execSync(`"${pipCmd}" install --only-binary=Pillow "Pillow>=10.0.0"`, {
      stdio: 'inherit',
      timeout: 120000,
    });
  } catch (err) {
    error(
      'Pillow could not be installed from a pre-built wheel for this Python/platform. ' +
      'On macOS install system libs then retry: brew install libjpeg zlib'
    );
  }
  
  log('Installing Python dependencies (this may take a few minutes)...');
  try {
    execSync(`"${pipCmd}" install -r "${requirementsPath}" --prefer-binary --no-cache-dir`, {
      stdio: 'inherit',
      timeout: 600000, // 10 minutes
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
  } catch (err) {
    error(`Failed to install dependencies: ${err.message}`);
  }
  
  // Verify installation
  log('Verifying installation...');
  const pythonExe = PLATFORM === 'win32'
    ? path.join(BUNDLED_VENV_DIR, 'Scripts', 'python.exe')
    : path.join(BUNDLED_VENV_DIR, 'bin', 'python');
  
  try {
    execSync(`"${pythonExe}" -c "import uvicorn; import fastapi; import sqlalchemy; import pydantic"`, {
      stdio: 'ignore',
      timeout: 10000,
    });
    log('✓ All critical packages verified');
  } catch (err) {
    error(`Verification failed: ${err.message}`);
  }

  // Replace symlinks with file copies so macOS codesign --verify does not fail
  if (PLATFORM === 'darwin') {
    log('Resolving symlinks in bundled venv for macOS code signing...');
    resolveSymlinksInDir(BUNDLED_VENV_DIR);
  }
  
  log(`Bundled venv created successfully at: ${BUNDLED_VENV_DIR}`);
  log('This venv will be included in the installer - no Python installation required!');
}

// Run if called directly
if (require.main === module) {
  buildBundledVenv().catch((err) => {
    error(err.message);
  });
}

module.exports = { buildBundledVenv };
