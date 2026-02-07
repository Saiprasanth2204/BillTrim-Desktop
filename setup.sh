#!/bin/bash
# Setup script for BillTrim Desktop development

set -e

echo "🚀 Setting up BillTrim Desktop..."

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.9+ first."
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo "✅ Python version: $(python3 --version)"

# Install root dependencies
echo ""
echo "📦 Installing Electron dependencies..."
npm install

# Install frontend dependencies
echo ""
echo "📦 Installing frontend dependencies..."
cd frontend
npm install
cd ..

# Setup backend
echo ""
echo "🐍 Setting up backend..."
cd backend

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate

echo "Installing Python dependencies..."
pip install -q -r requirements.txt

cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "To run in development mode:"
echo "  1. Terminal 1: ./run-backend.sh"
echo "  2. Terminal 2: ./run-frontend.sh"
echo "  3. Terminal 3: npm run electron:dev"
echo ""
echo "To build installers, see BUILD.md"
