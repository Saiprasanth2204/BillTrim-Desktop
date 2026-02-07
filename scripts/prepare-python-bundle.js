#!/usr/bin/env node
/**
 * Script to prepare Python bundle for distribution
 * This downloads/bundles Python runtime and pre-installs dependencies
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const https = require('https');
const http = require('http');

const PLATFORM = process.platform;
const ARCH = process.arch;
const PYTHON_VERSION = '3.11.9'; // Use a stable Python version
const BUILD_DIR = path.join(__dirname, '..', 'build');
const PYTHON_BUNDLE_DIR = path.join(BUILD_DIR, 'python-bundle');

// Python download URLs
const PYTHON_URLS = {
  'darwin-x64': `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg`,
  'darwin-arm64': `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg`,
  'win32-x64': `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe`,
  'win32-ia32': `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}.exe`,
};

function log(message) {
  console.log(`[Python Bundle] ${message}`);
}

function error(message) {
  console.error(`[Python Bundle ERROR] ${message}`);
  process.exit(1);
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const protocol = url.startsWith('https') ? https : http;
    
    protocol.get(url, (response) => {
      if (response.statusCode === 302 || response.statusCode === 301) {
        // Follow redirect
        return downloadFile(response.headers.location, dest).then(resolve).catch(reject);
      }
      
      if (response.statusCode !== 200) {
        reject(new Error(`Failed to download: ${response.statusCode}`));
        return;
      }
      
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      fs.unlinkSync(dest);
      reject(err);
    });
  });
}

async function preparePythonBundle() {
  log('Preparing Python bundle for distribution...');
  log(`Platform: ${PLATFORM}, Arch: ${ARCH}`);
  
  ensureDir(BUILD_DIR);
  ensureDir(PYTHON_BUNDLE_DIR);
  
  const platformKey = `${PLATFORM}-${ARCH}`;
  
  if (PLATFORM === 'darwin') {
    log('macOS detected - using system Python or Homebrew Python');
    log('For production, Python will be bundled from system installation');
    
    // For macOS, we'll use the system Python or create a portable Python
    // Check if Python 3 is available
    try {
      const pythonVersion = execSync('python3 --version', { encoding: 'utf8' }).trim();
      log(`Found system Python: ${pythonVersion}`);
      
      // Find Python executable
      const pythonPath = execSync('which python3', { encoding: 'utf8' }).trim();
      log(`Python path: ${pythonPath}`);
      
      // Create a symlink or copy Python to bundle directory
      const bundlePythonDir = path.join(PYTHON_BUNDLE_DIR, 'bin');
      ensureDir(bundlePythonDir);
      
      // For macOS, we'll create a script that uses system Python
      // In production, we'll bundle a portable Python or use PyInstaller
      log('Note: For true self-contained distribution, consider using PyInstaller or bundling portable Python');
      
    } catch (err) {
      error(`Python 3 not found. Please install Python 3.9+: ${err.message}`);
    }
  } else if (PLATFORM === 'win32') {
    log('Windows detected - preparing Python bundle');
    
    // For Windows, we can use embeddable Python
    const embeddableUrl = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-${ARCH === 'x64' ? 'amd64' : 'win32'}.zip`;
    const pythonZip = path.join(PYTHON_BUNDLE_DIR, 'python-embed.zip');
    
    log(`Downloading embeddable Python from: ${embeddableUrl}`);
    try {
      await downloadFile(embeddableUrl, pythonZip);
      log('Python downloaded successfully');
      
      // Extract zip (would need unzipper or similar)
      log('Note: Extract python-embed.zip and place in python-bundle directory');
    } catch (err) {
      log(`Warning: Could not download embeddable Python: ${err.message}`);
      log('Will use system Python as fallback');
    }
  } else {
    log(`Platform ${PLATFORM} not fully supported for Python bundling`);
    log('Will use system Python as fallback');
  }
  
  // Create venv with dependencies
  log('Creating virtual environment with dependencies...');
  const venvPath = path.join(PYTHON_BUNDLE_DIR, 'venv');
  const backendPath = path.join(__dirname, '..', 'backend');
  const requirementsPath = path.join(backendPath, 'requirements.txt');
  
  if (!fs.existsSync(requirementsPath)) {
    error(`Requirements file not found: ${requirementsPath}`);
  }
  
  // Use system Python to create venv
  const pythonCmd = PLATFORM === 'win32' ? 'python' : 'python3';
  
  try {
    // Create venv
    log('Creating virtual environment...');
    execSync(`${pythonCmd} -m venv "${venvPath}"`, {
      stdio: 'inherit',
      cwd: BUILD_DIR,
    });
    
    // Install dependencies
    const pipCmd = PLATFORM === 'win32'
      ? path.join(venvPath, 'Scripts', 'pip.exe')
      : path.join(venvPath, 'bin', 'pip');
    
    log('Installing Python dependencies...');
    execSync(`"${pipCmd}" install --upgrade pip`, {
      stdio: 'inherit',
      timeout: 120000,
    });
    
    execSync(`"${pipCmd}" install -r "${requirementsPath}" --prefer-binary`, {
      stdio: 'inherit',
      timeout: 300000,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    
    log('Python bundle prepared successfully!');
    log(`Venv location: ${venvPath}`);
    
  } catch (err) {
    error(`Failed to create venv: ${err.message}`);
  }
}

// Run if called directly
if (require.main === module) {
  preparePythonBundle().catch((err) => {
    error(err.message);
  });
}

module.exports = { preparePythonBundle };
