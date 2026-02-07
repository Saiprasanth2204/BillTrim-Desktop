const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow = null;
let backendProcess = null;
let backendWasReady = false; // true once backend has ever been ready (for auto-restart on exit)
let backendRestartCount = 0;  // limit auto-restart to one attempt
let devToolsOpened = false; // Flag to prevent opening DevTools multiple times
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;

// Determine if we're in development or production
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

// App data directory for storing database, uploads, and logs
const appDataPath = app.getPath('userData');
const dataDir = path.join(appDataPath, 'data');
const uploadsDir = path.join(appDataPath, 'uploads');
const logsDir = path.join(appDataPath, 'logs');
const licenseFilePath = path.join(appDataPath, 'license.key');

// Ensure data directories exist
[dataDir, uploadsDir, logsDir].forEach(dir => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
});

// Production log file (main process + backend output)
let logStream = null;
function getLogStream() {
  if (logStream) return logStream;
  try {
    const logPath = path.join(logsDir, 'app.log');
    logStream = fs.createWriteStream(logPath, { flags: 'a' });
  } catch (e) {
    console.error('Could not create log file:', e);
  }
  return logStream;
}
function writeLog(prefix, msg) {
  const line = `[${new Date().toISOString()}] [${prefix}] ${msg}\n`;
  const s = getLogStream();
  if (s && s.writable) {
    s.write(line);
  }
}

// License validation
const VALID_LICENSE_KEY = '95001958328698042535';

function validateLicense(licenseKey) {
  // Remove all non-digit characters
  const normalized = licenseKey.replace(/\D/g, '');
  return normalized === VALID_LICENSE_KEY;
}

function getStoredLicense() {
  try {
    if (fs.existsSync(licenseFilePath)) {
      const licenseKey = fs.readFileSync(licenseFilePath, 'utf8').trim();
      return validateLicense(licenseKey) ? licenseKey : null;
    }
  } catch (error) {
    console.error('Error reading license file:', error);
  }
  return null;
}

function storeLicenseKey(licenseKey) {
  try {
    const normalized = licenseKey.replace(/\D/g, '');
    if (validateLicense(normalized)) {
      fs.writeFileSync(licenseFilePath, normalized, 'utf8');
      return true;
    }
    return false;
  } catch (error) {
    console.error('Error storing license:', error);
    return false;
  }
}

// Paths
const backendPath = isDev 
  ? path.join(__dirname, '..', 'backend')
  : path.join(process.resourcesPath, 'backend');

// In production, files are packaged in app.asar, so we need to use app.getAppPath()
// For frontend/dist, it should be accessible via the app path
const frontendPath = isDev
  ? path.join(__dirname, '..', 'frontend', 'dist')
  : path.join(app.getAppPath(), 'frontend', 'dist');

console.log('=== Electron Startup Debug ===');
console.log('Is dev mode:', isDev);
console.log('App packaged:', app.isPackaged);
console.log('App path:', app.getAppPath());
console.log('Frontend path:', frontendPath);
console.log('Backend path:', backendPath);
console.log('Resources path:', process.resourcesPath);
console.log('__dirname:', __dirname);
console.log('============================');

// Detect Electron process architecture
const getElectronArch = () => {
  // process.arch can be 'x64' or 'arm64'
  // But we need to check the actual architecture of the running process
  if (process.platform === 'darwin') {
    // On macOS, check if we're running under Rosetta (x86_64 on arm64 Mac)
    try {
      const { execSync } = require('child_process');
      const arch = execSync('arch', { encoding: 'utf8' }).trim();
      return arch === 'arm64' ? 'arm64' : 'x64';
    } catch (e) {
      // Fallback to process.arch
      return process.arch === 'arm64' ? 'arm64' : 'x64';
    }
  }
  return process.arch === 'arm64' ? 'arm64' : 'x64';
};

// Python executable path
const getPythonExecutable = () => {
  const electronArch = getElectronArch();
  console.log(`Electron architecture: ${electronArch}`);
  
  if (isDev) {
    // In development, use system Python or venv
    const venvPython = path.join(backendPath, 'venv', 'bin', 'python');
    if (process.platform === 'win32') {
      const venvPythonWin = path.join(backendPath, 'venv', 'Scripts', 'python.exe');
      if (fs.existsSync(venvPythonWin)) return venvPythonWin;
    } else {
      if (fs.existsSync(venvPython)) return venvPython;
    }
    return process.platform === 'win32' ? 'python.exe' : 'python3';
  } else {
    // In production, ALWAYS use bundled venv first (self-contained installation)
    const bundledVenvPython = process.platform === 'win32'
      ? path.join(process.resourcesPath, 'bundled-venv', 'Scripts', 'python.exe')
      : path.join(process.resourcesPath, 'bundled-venv', 'bin', 'python');
    
    if (fs.existsSync(bundledVenvPython)) {
      console.log(`Using bundled Python venv: ${bundledVenvPython}`);
      return bundledVenvPython;
    }
    
    // Fallback: If bundled venv doesn't exist (shouldn't happen in production)
    // Try to find system Python as last resort
    console.warn('Bundled venv not found, falling back to system Python (this should not happen in production)');
    
    if (process.platform === 'win32') {
      return 'python.exe';
    } else {
      // Try common Python locations on macOS
      const commonPaths = electronArch === 'arm64' ? [
        '/opt/homebrew/bin/python3',
        '/usr/local/bin/python3',
        '/usr/bin/python3',
      ] : [
        '/usr/local/bin/python3',
        '/opt/homebrew/bin/python3',
        '/usr/bin/python3',
      ];
      
      for (const pythonPath of commonPaths) {
        if (fs.existsSync(pythonPath)) {
          console.log(`Found system Python at: ${pythonPath}`);
          return pythonPath;
        }
      }
      
      // Last resort
      return 'python3';
    }
  }
};

// Setup Python virtual environment in production
// NOTE: In production, we use the pre-bundled venv, so this function is mainly for fallback
async function setupProductionVenv() {
  if (isDev) {
    return null; // Use existing venv in dev mode
  }
  
  // Check if bundled venv exists (it should in production)
  const bundledVenvPython = process.platform === 'win32'
    ? path.join(process.resourcesPath, 'bundled-venv', 'Scripts', 'python.exe')
    : path.join(process.resourcesPath, 'bundled-venv', 'bin', 'python');
  
  if (fs.existsSync(bundledVenvPython)) {
    console.log('Using pre-bundled Python venv (no installation needed)');
    return bundledVenvPython;
  }
  
  // Fallback: If bundled venv doesn't exist, create one at runtime
  // This should only happen if the build process didn't include the bundled venv
  console.warn('Bundled venv not found - creating runtime venv (this should not happen in production)');
  
  const venvPath = path.join(appDataPath, 'venv');
  const venvPython = process.platform === 'win32' 
    ? path.join(venvPath, 'Scripts', 'python.exe')
    : path.join(venvPath, 'bin', 'python');
  
  // Check if venv already exists
  if (fs.existsSync(venvPython)) {
    try {
      const { execSync } = require('child_process');
      execSync(`"${venvPython}" -c "import uvicorn"`, { 
        stdio: 'ignore', 
        timeout: 5000,
        env: { ...process.env }
      });
      console.log('Runtime venv exists and has packages');
      return venvPython;
    } catch (e) {
      console.log('Runtime venv exists but missing packages, reinstalling...');
      try {
        fs.rmSync(venvPath, { recursive: true, force: true });
      } catch (rmError) {
        console.warn('Could not remove old venv:', rmError.message);
      }
    }
  }
  
  // Create venv and install packages (fallback only)
  console.log('Setting up runtime Python virtual environment...');
  console.log('This may take a few minutes...');
  const requirementsFile = path.join(backendPath, 'requirements.txt');
  const systemPython = getPythonExecutable();
  
  if (!fs.existsSync(requirementsFile)) {
    console.warn('Requirements file not found');
    return null;
  }
  
  try {
    const { execSync } = require('child_process');
    
    // Create venv
    console.log('Creating virtual environment...');
    execSync(`"${systemPython}" -m venv "${venvPath}"`, {
      stdio: 'inherit',
      env: { ...process.env },
      timeout: 60000,
    });
    
    // Install packages
    const pipCmd = process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', 'pip.exe')
      : path.join(venvPath, 'bin', 'pip');
    
    console.log('Installing Python packages...');
    execSync(`"${pipCmd}" install --upgrade pip`, {
      stdio: 'inherit',
      timeout: 60000,
    });
    
    execSync(`"${pipCmd}" install -r "${requirementsFile}" --prefer-binary`, {
      stdio: 'inherit',
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      timeout: 300000,
    });
    
    if (fs.existsSync(venvPython)) {
      console.log('Runtime venv setup complete');
      return venvPython;
    }
  } catch (error) {
    console.error('Failed to setup runtime venv:', error.message);
    return null;
  }
  
  return null;
}

// Check and kill any existing backend process on port 8765
async function killExistingBackend() {
  return new Promise((resolve) => {
    const { exec } = require('child_process');
    const command = process.platform === 'darwin' || process.platform === 'linux'
      ? `lsof -ti:${BACKEND_PORT}`
      : `netstat -ano | findstr :${BACKEND_PORT}`;
    
    exec(command, (error, stdout, stderr) => {
      if (error || !stdout.trim()) {
        // No process found, nothing to kill
        console.log('No existing backend process found on port', BACKEND_PORT);
        resolve();
        return;
      }
      
      const pids = stdout.trim().split('\n').filter(pid => pid.trim());
      if (pids.length === 0) {
        resolve();
        return;
      }
      
      console.log(`Found existing backend process(es) on port ${BACKEND_PORT}:`, pids);
      
      // Kill processes
      const killCommand = process.platform === 'darwin' || process.platform === 'linux'
        ? `kill -9 ${pids.join(' ')}`
        : `taskkill /F /PID ${pids.join(' /PID ')}`;
      
      exec(killCommand, (killError) => {
        if (killError) {
          console.warn('Failed to kill existing backend process:', killError.message);
        } else {
          console.log('Killed existing backend process(es)');
          // Wait a moment for port to be released
          setTimeout(resolve, 1000);
        }
        resolve();
      });
    });
  });
}

// Start backend server
function startBackend() {
  return new Promise(async (resolve, reject) => {
    // Kill any existing backend process first
    await killExistingBackend();
    
    // Setup production venv first if needed
    let productionPython = null;
    if (!isDev) {
      try {
        productionPython = await setupProductionVenv();
      } catch (error) {
        console.warn('Failed to setup production venv, using system Python:', error.message);
      }
    }
    
    // Use production venv Python if available, otherwise use bundled/system Python
    // In production, productionPython should be the bundled venv
    let pythonExec = productionPython || getPythonExecutable();
    
    // In production, if we don't have a Python executable, show error
    if (!isDev && !pythonExec) {
      const error = new Error('Python executable not found. The application requires Python to run.\n\nPlease ensure Python 3.9+ is installed, or contact support if this is a packaged application.');
      console.error(error.message);
      reject(error);
      return;
    }
    const backendScript = path.join(backendPath, 'run_server.py');
    
    console.log('=== Backend Startup Debug ===');
    console.log('Python executable:', pythonExec);
    console.log('Python exists:', fs.existsSync(pythonExec));
    console.log('Backend path:', backendPath);
    console.log('Backend path exists:', fs.existsSync(backendPath));
    console.log('Backend script:', backendScript);
    console.log('Backend script exists:', fs.existsSync(backendScript));
    console.log('Is dev mode:', isDev);
    console.log('Using production venv:', productionPython !== null);
    console.log('============================');

    // Set environment variables
    // In production, ensure PATH includes common Python locations
    let pathEnv = process.env.PATH || '';
    if (!isDev && process.platform === 'darwin') {
      const pythonPaths = [
        '/usr/local/bin',
        '/opt/homebrew/bin',
        '/usr/bin',
        '/Library/Frameworks/Python.framework/Versions/3.13/bin',
        '/Library/Frameworks/Python.framework/Versions/3.12/bin',
        '/Library/Frameworks/Python.framework/Versions/3.11/bin',
        '/Library/Frameworks/Python.framework/Versions/3.10/bin',
        '/Library/Frameworks/Python.framework/Versions/3.9/bin',
      ];
      // Add Python paths to PATH if not already present
      pythonPaths.forEach(pythonPath => {
        if (fs.existsSync(pythonPath) && !pathEnv.includes(pythonPath)) {
          pathEnv = `${pythonPath}:${pathEnv}`;
        }
      });
    }
    
    const env = {
      ...process.env,
      PATH: pathEnv,
      PYTHONPATH: backendPath,
      PYTHONUNBUFFERED: '1',
      // Set data directory for production
      DATABASE_PATH: isDev ? undefined : path.join(dataDir, 'billtrim.db'),
      UPLOAD_DIR: isDev ? undefined : uploadsDir,
      // Backend logs go to userData/logs/backend.log
      BILLTRIM_LOG_DIR: logsDir,
    };
    
    // Remove undefined values
    Object.keys(env).forEach(key => {
      if (env[key] === undefined) {
        delete env[key];
      }
    });

    // Change working directory to backend
    const cwd = backendPath;

    // Verify Python executable exists and is executable
    // If it's not an absolute path, try to resolve it
    let resolvedPythonExec = pythonExec;
    if (!path.isAbsolute(pythonExec)) {
      // First, try common Python locations directly
      if (process.platform === 'darwin') {
        const commonPaths = [
          '/usr/local/bin/python3',
          '/opt/homebrew/bin/python3',
          '/usr/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.9/bin/python3',
        ];
        
        for (const pythonPath of commonPaths) {
          if (fs.existsSync(pythonPath)) {
            resolvedPythonExec = pythonPath;
            console.log(`Found Python at: ${pythonPath}`);
            break;
          }
        }
      }
      
      // If still not found, try to find the executable in PATH
      if (resolvedPythonExec === pythonExec) {
        const { execSync } = require('child_process');
        try {
          // Use the updated PATH from env
          const foundPath = execSync(`which ${pythonExec}`, { 
            encoding: 'utf8',
            env: { ...process.env, PATH: pathEnv }
          }).trim();
          if (foundPath && fs.existsSync(foundPath)) {
            resolvedPythonExec = foundPath;
            console.log(`Resolved Python executable from PATH: ${pythonExec} -> ${resolvedPythonExec}`);
          }
        } catch (e) {
          console.warn(`Could not resolve ${pythonExec} from PATH:`, e.message);
        }
      }
    }
    
    if (!fs.existsSync(resolvedPythonExec)) {
      const error = new Error(`Python executable not found: ${pythonExec} (resolved: ${resolvedPythonExec})\n\nPlease ensure Python 3.9+ is installed and available.\nOn macOS, you can install Python via Homebrew: brew install python3\nOr download from: https://www.python.org/downloads/`);
      console.error(error.message);
      console.error('Common Python locations checked:');
      if (process.platform === 'darwin') {
        const commonPaths = [
          '/usr/local/bin/python3',
          '/opt/homebrew/bin/python3',
          '/usr/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3',
          '/Library/Frameworks/Python.framework/Versions/3.9/bin/python3',
        ];
        commonPaths.forEach(p => {
          console.error(`  ${p}: ${fs.existsSync(p) ? 'EXISTS ✓' : 'NOT FOUND ✗'}`);
        });
      }
      reject(error);
      return;
    }

    // Check if executable (Unix-like systems)
    if (process.platform !== 'win32') {
      try {
        fs.accessSync(resolvedPythonExec, fs.constants.X_OK);
      } catch (err) {
        const error = new Error(`Python executable is not executable: ${resolvedPythonExec}`);
        console.error(error.message);
        reject(error);
        return;
      }
    }
    
    // Use resolved path
    pythonExec = resolvedPythonExec;

    // On macOS, ensure Python runs in the correct architecture
    // The issue: Electron might be x86_64 (Rosetta) but Python is arm64
    // Solution: Use arch command to force Python to run in native arm64 mode
    let spawnCommand = pythonExec;
    let spawnArgs = [backendScript];
    
    if (process.platform === 'darwin') {
      const electronArch = getElectronArch();
      const systemArch = require('os').arch();
      
      console.log(`Electron arch: ${electronArch}, System arch: ${systemArch}`);
      
      // If we're on Apple Silicon (arm64) but Electron is running as x86_64,
      // we need to ensure Python runs natively as arm64 to match its packages
      if (systemArch === 'arm64' && electronArch === 'x64') {
        console.log('Detected x86_64 Electron on arm64 Mac - forcing Python to run as arm64');
        // Use arch command to force arm64 execution
        spawnCommand = 'arch';
        spawnArgs = ['-arm64', pythonExec, backendScript];
      }
    }
    
    backendProcess = spawn(spawnCommand, spawnArgs, {
      cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let backendReady = false;
    let errorOutput = [];
    let stdoutOutput = [];
    let sawStartupBegin = false;
    let sawMigrations = false;
    let healthCheckScheduled = false;
    let timeoutId = null;
    
    // Helper to resolve and clear timeout (prevents multiple resolutions)
    const resolveWithCleanup = () => {
      if (!backendReady) {
        backendReady = true;
        backendWasReady = true; // remember for auto-restart if backend exits later
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        resolve();
      }
    };

    backendProcess.stdout.on('data', (data) => {
      const output = data.toString();
      stdoutOutput.push(output);
      writeLog('Backend', output.trim());
      console.log('[Backend]', output);
      
      // Track startup progress
      if (output.includes('Started server process')) {
        sawStartupBegin = true;
        console.log('Detected: Server process started');
      }
      if (output.includes('migration') || output.includes('alembic') || output.includes('alembic.runtime.migration')) {
        sawMigrations = true;
        console.log('Detected: Migrations running');
      }
      
      // Check if server is ready - uvicorn logs "Uvicorn running on" when ready
      if (output.includes('Uvicorn running on')) {
        if (!backendReady && !healthCheckScheduled) {
          console.log('Detected "Uvicorn running on" - checking health...');
          healthCheckScheduled = true;
          // Wait a moment then check health
          setTimeout(async () => {
            if (!backendReady) {
              try {
                const http = require('http');
                await new Promise((resolveHealth, rejectHealth) => {
                  const req = http.get(`${BACKEND_URL}/health`, (res) => {
                    if (res.statusCode === 200) {
                      console.log('Backend is ready (health check passed)!');
                      resolveWithCleanup();
                    } else {
                      rejectHealth(new Error(`Health check returned ${res.statusCode}`));
                    }
                  });
                  req.on('error', rejectHealth);
                  req.setTimeout(3000, () => {
                    req.destroy();
                    rejectHealth(new Error('Health check timeout'));
                  });
                });
              } catch (error) {
                console.log('Health check failed, but uvicorn is running - assuming ready:', error.message);
                resolveWithCleanup();
              }
            }
          }, 2000);
        }
      }
      
      // Also check for our custom startup complete message
      if (output.includes('=== Application startup complete ===')) {
        if (!backendReady && !healthCheckScheduled) {
          console.log('Detected startup complete message - checking health...');
          healthCheckScheduled = true;
          // Wait a moment for server to fully start, then check health
          setTimeout(async () => {
            if (!backendReady) {
              try {
                const http = require('http');
                await new Promise((resolveHealth, rejectHealth) => {
                  const req = http.get(`${BACKEND_URL}/health`, (res) => {
                    if (res.statusCode === 200) {
                      console.log('Backend is ready (health check passed after startup complete)');
                      resolveWithCleanup();
                    } else {
                      rejectHealth(new Error(`Health check returned ${res.statusCode}`));
                    }
                  });
                  req.on('error', rejectHealth);
                  req.setTimeout(3000, () => {
                    req.destroy();
                    rejectHealth(new Error('Health check timeout'));
                  });
                });
              } catch (error) {
                // If health check fails but we see startup messages, assume ready anyway
                console.log('Health check failed but startup complete detected, assuming ready:', error.message);
                resolveWithCleanup();
              }
            }
          }, 2000); // Wait 2 seconds after seeing startup complete
        }
      }
    });

    backendProcess.stderr.on('data', (data) => {
      const output = data.toString();
      errorOutput.push(output);
      writeLog('Backend(stderr)', output.trim());
      console.error('[Backend Error]', output);
      
      // Track startup progress from stderr (some frameworks log to stderr)
      if (output.includes('Started server process')) {
        sawStartupBegin = true;
        console.log('Detected (stderr): Server process started');
      }
      if (output.includes('migration') || output.includes('alembic') || output.includes('alembic.runtime.migration')) {
        sawMigrations = true;
        console.log('Detected (stderr): Migrations running');
      }
      
      // Some frameworks log to stderr even for normal messages
      // Check for startup completion messages
      if ((output.includes('Uvicorn running on') || 
          output.includes('=== Application startup complete ===')) && 
          !backendReady && !healthCheckScheduled) {
        console.log('Detected startup message in stderr - checking health...');
        healthCheckScheduled = true;
        // Wait a moment and check health
        setTimeout(async () => {
          if (!backendReady) {
            try {
              const http = require('http');
              await new Promise((resolveHealth, rejectHealth) => {
                const req = http.get(`${BACKEND_URL}/health`, (res) => {
                  if (res.statusCode === 200) {
                    console.log('Backend is ready (health check passed from stderr)');
                    resolveWithCleanup();
                  } else {
                    rejectHealth(new Error(`Health check returned ${res.statusCode}`));
                  }
                });
                req.on('error', rejectHealth);
                req.setTimeout(3000, () => {
                  req.destroy();
                  rejectHealth(new Error('Health check timeout'));
                });
              });
            } catch (error) {
              console.log('Health check failed but startup detected, assuming ready:', error.message);
              resolveWithCleanup();
            }
          }
        }, 2000);
      }
    });

    backendProcess.on('error', (error) => {
      console.error('Failed to start backend:', error);
      console.error('Python executable:', pythonExec);
      console.error('Backend script:', backendScript);
      console.error('Backend path:', backendPath);
      console.error('Working directory:', cwd);
      reject(error);
    });

    backendProcess.on('exit', (code, signal) => {
      console.log(`Backend process exited with code ${code}, signal ${signal}`);
      if (code !== 0 && code !== null) {
        if (!backendReady) {
          const errorMsg = `Backend exited with code ${code}`;
          const fullError = [
            errorMsg,
            '--- STDOUT ---',
            ...stdoutOutput,
            '--- STDERR ---',
            ...errorOutput,
          ].join('\n');
          console.error('Full backend output:', fullError);
          reject(new Error(fullError));
        } else if (backendWasReady && backendRestartCount < 1) {
          // Backend was running and exited unexpectedly; try to restart once
          backendRestartCount += 1;
          console.log('Backend stopped unexpectedly. Attempting auto-restart...');
          setImmediate(() => {
            startBackend()
              .then(() => {
                console.log('Backend restarted successfully.');
              })
              .catch((err) => {
                console.error('Backend restart failed:', err && err.message ? err.message : err);
              });
          });
        }
      }
    });

    // Timeout after 30 seconds - try health check as fallback
    timeoutId = setTimeout(async () => {
      if (backendReady) {
        return; // Already resolved, don't do anything
      }
      
      // Check if process is still running
      if (backendProcess && !backendProcess.killed && backendProcess.exitCode === null) {
        // Process is still running, try health check once
        console.log('Backend process is still running after 30s, checking health endpoint...');
        console.log(`Saw startup begin: ${sawStartupBegin}, Saw migrations: ${sawMigrations}`);
        
        try {
          const http = require('http');
          await new Promise((resolveHealth, rejectHealth) => {
            const req = http.get(`${BACKEND_URL}/health`, (res) => {
              if (res.statusCode === 200) {
                console.log('Health check passed in timeout handler, backend is ready!');
                resolveWithCleanup();
              } else {
                rejectHealth(new Error(`Health check returned ${res.statusCode}`));
              }
            });
            req.on('error', rejectHealth);
            req.setTimeout(5000, () => {
              req.destroy();
              rejectHealth(new Error('Health check timeout'));
            });
          });
        } catch (healthError) {
          // Health check failed, but process is running - assume ready anyway
          console.log('Health check failed in timeout handler, but process is running - assuming ready:', healthError.message);
          resolveWithCleanup();
        }
      } else {
        const errorMsg = 'Backend startup timeout - process may have exited';
        const fullError = [
          errorMsg,
          `Process killed: ${backendProcess?.killed}`,
          `Exit code: ${backendProcess?.exitCode}`,
          `Saw startup begin: ${sawStartupBegin}`,
          `Saw migrations: ${sawMigrations}`,
          '--- STDOUT ---',
          ...stdoutOutput.slice(-50), // Last 50 lines
          '--- STDERR ---',
          ...errorOutput.slice(-50), // Last 50 lines
        ].join('\n');
        console.error(fullError);
        if (!backendReady) {
          if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
          }
          reject(new Error(fullError));
        }
      }
    }, 30000);
  });
}

// Wait for backend to be ready
async function waitForBackend(maxAttempts = 30) {
  const http = require('http');
  
  for (let i = 0; i < maxAttempts; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(`${BACKEND_URL}/health`, (res) => {
          if (res.statusCode === 200) {
            resolve(true);
          } else {
            reject(new Error(`Status: ${res.statusCode}`));
          }
        });
        req.on('error', reject);
        req.setTimeout(2000, () => {
          req.destroy();
          reject(new Error('Timeout'));
        });
      });
      return true;
    } catch (error) {
      // Backend not ready yet, wait and retry
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return false;
}

// Create main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    // Icon will be set by electron-builder based on platform
    show: false, // Don't show until ready
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
  });

  // Load the frontend
  // In production, files are in app.asar, so we need to use the correct path
  let indexPath;
  if (isDev) {
    indexPath = path.join(frontendPath, 'index.html');
  } else {
    // In production, use app.getAppPath() which points to the asar archive
    // Files inside asar can be accessed via normal paths
    indexPath = path.join(app.getAppPath(), 'frontend', 'dist', 'index.html');
  }
  
  console.log('Loading frontend from:', indexPath);
  console.log('Frontend path exists:', fs.existsSync(indexPath));
  console.log('Frontend directory:', frontendPath);
  console.log('App path:', app.getAppPath());
  
  // Helper function to open DevTools (only once, docked)
  const openDevToolsOnce = () => {
    if (!devToolsOpened && mainWindow && !mainWindow.isDestroyed() && isDev) {
      devToolsOpened = true;
      // Open DevTools docked to the right (not as separate window)
      mainWindow.webContents.openDevTools({ mode: 'right' });
    }
  };
  
  // Inject desktop mode variables as early as possible
  // Use did-start-loading to inject before any scripts run
  mainWindow.webContents.once('did-start-loading', () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed
    }
    mainWindow.webContents.executeJavaScript(`
      window.__DESKTOP_MODE__ = true;
      window.__API_URL__ = 'http://localhost:8765/api/v1';
      console.log('Desktop mode initialized (early injection)');
    `).catch(err => console.error('Failed to inject desktop vars early:', err));
  });

  // Also inject on dom-ready as backup
  mainWindow.webContents.once('dom-ready', () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed
    }
    mainWindow.webContents.executeJavaScript(`
      if (typeof window.__DESKTOP_MODE__ === 'undefined') {
        window.__DESKTOP_MODE__ = true;
        window.__API_URL__ = 'http://localhost:8765/api/v1';
        console.log('Desktop mode initialized (dom-ready fallback)');
      } else {
        console.log('Desktop mode already initialized:', window.__DESKTOP_MODE__);
      }
    `).catch(err => console.error('Failed to verify desktop vars:', err));
  });

  // Try to load the file - loadFile handles asar archives automatically
  (async () => {
    try {
      if (!mainWindow || mainWindow.isDestroyed()) {
        return; // Window was closed
      }
      await mainWindow.loadFile(indexPath);
      console.log('Successfully loaded index.html');
    } catch (error) {
      if (!mainWindow || mainWindow.isDestroyed()) {
        return; // Window was closed
      }
      console.error('Failed to load index.html:', error);
      console.error('Error details:', error.message);
      
      // Try using loadURL with file:// protocol as fallback
      try {
        if (!mainWindow || mainWindow.isDestroyed()) {
          return; // Window was closed
        }
        const fileUrl = `file://${indexPath}`;
        console.log('Trying file:// URL:', fileUrl);
        await mainWindow.loadURL(fileUrl);
      } catch (urlError) {
        if (!mainWindow || mainWindow.isDestroyed()) {
          return; // Window was closed
        }
        console.error('File URL also failed:', urlError);
        // Show window anyway so user can see what's happening
        mainWindow.show();
        openDevToolsOnce();
      }
    }
  })();

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed
    }
    console.log('Window ready to show');
    mainWindow.show();
  });

  // Handle page load errors
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed
    }
    console.error('Page failed to load:', errorCode, errorDescription, validatedURL);
    // Show window anyway so user can see error
    mainWindow.show();
    openDevToolsOnce();
  });

  // Handle console messages from renderer
  mainWindow.webContents.on('console-message', (event, level, message) => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed
    }
    console.log(`[Renderer ${level}]:`, message);
  });

  // Open DevTools in development mode only (docked, not separate window)
  openDevToolsOnce();

  // Check if page loaded successfully after a delay
  setTimeout(() => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return; // Window was closed, don't try to access it
    }
    mainWindow.webContents.executeJavaScript(`
      (function() {
        const root = document.getElementById('root');
        if (!root || root.innerHTML.trim() === '') {
          console.error('React app not mounted - root element is empty');
          return false;
        }
        return true;
      })();
    `).then((mounted) => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        return; // Window was closed
      }
      if (!mounted) {
        console.error('React app appears not to be mounted - opening DevTools for debugging');
        openDevToolsOnce();
      }
    }).catch((err) => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        return; // Window was closed
      }
      console.error('Error checking React mount:', err);
      openDevToolsOnce();
    });
  }, 3000);

  // Fallback: Show window after 5 seconds even if ready-to-show didn't fire
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      console.log('Window not shown after 5 seconds, forcing show');
      mainWindow.show();
      openDevToolsOnce(); // Open DevTools to debug (only in dev mode)
    }
  }, 5000);

  mainWindow.on('closed', () => {
    mainWindow = null;
    devToolsOpened = false; // Reset flag when window closes
  });
}

// App lifecycle
app.whenReady().then(async () => {
  try {
    console.log('Starting backend server...');
    await startBackend();
    console.log('Backend started, waiting for health check...');
    
    const backendReady = await waitForBackend();
    if (backendReady) {
      console.log('Backend is ready!');
      createWindow();
    } else {
      console.error('Backend failed to become ready');
      app.quit();
    }
  } catch (error) {
    console.error('Failed to start application:', error);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  // Kill backend process
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
  
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('before-quit', () => {
  // Ensure backend is killed
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});

// Handle IPC messages
ipcMain.handle('get-backend-url', () => {
  return BACKEND_URL;
});

// Check backend health status
ipcMain.handle('check-backend-health', async () => {
  const http = require('http');
  return new Promise((resolve) => {
    const req = http.get(`${BACKEND_URL}/health`, (res) => {
      resolve({ status: res.statusCode === 200 ? 'healthy' : 'unhealthy', code: res.statusCode });
    });
    req.on('error', () => {
      resolve({ status: 'unreachable', code: null });
    });
    req.setTimeout(2000, () => {
      req.destroy();
      resolve({ status: 'timeout', code: null });
    });
  });
});

// Restart backend
ipcMain.handle('restart-backend', async () => {
  try {
    // Kill existing backend
    if (backendProcess) {
      backendProcess.kill();
      backendProcess = null;
    }
    await killExistingBackend();
    
    // Start backend again
    await startBackend();
    const backendReady = await waitForBackend();
    return { success: backendReady };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// License management
ipcMain.handle('check-license', async () => {
  const storedLicense = getStoredLicense();
  return storedLicense !== null;
});

ipcMain.handle('store-license', async (event, licenseKey) => {
  return storeLicenseKey(licenseKey);
});

ipcMain.handle('clear-license', async () => {
  try {
    if (fs.existsSync(licenseFilePath)) {
      fs.unlinkSync(licenseFilePath);
    }
    return true;
  } catch (error) {
    console.error('Error clearing license file:', error);
    return false;
  }
});
