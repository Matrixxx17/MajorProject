#!/bin/bash

# Python Assistant - Setup Script
# This script sets up the complete development environment

set -e

echo "=========================================="
echo "Python Assistant - Setup Script"
echo "=========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "Checking prerequisites..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION found"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is not installed${NC}"
    exit 1
fi

NODE_VERSION=$(node --version)
echo -e "${GREEN}✓${NC} Node.js $NODE_VERSION found"

# Check npm
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed${NC}"
    exit 1
fi

NPM_VERSION=$(npm --version)
echo -e "${GREEN}✓${NC} npm $NPM_VERSION found"

echo ""
echo "=========================================="
echo "Setting up Backend"
echo "=========================================="
echo ""

cd backend

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}✓${NC} Backend setup complete"

cd ..

echo ""
echo "=========================================="
echo "Setting up Extension"
echo "=========================================="
echo ""

# Install Node.js dependencies
echo "Installing Node.js dependencies..."
npm install

# Compile TypeScript
echo "Compiling TypeScript..."
npm run compile

echo -e "${GREEN}✓${NC} Extension setup complete"

echo ""
echo "=========================================="
echo "Checking Optional Dependencies"
echo "=========================================="
echo ""

# Check for Ollama
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓${NC} Ollama is installed"
else
    echo -e "${YELLOW}!${NC} Ollama is not installed (optional for test refinement)"
    echo "  Install from: https://ollama.ai"
fi

# Check for CUDA
if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}✓${NC} CUDA is available"
    nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1
else
    echo -e "${YELLOW}!${NC} CUDA is not available (GPU acceleration disabled)"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start the backend server:"
echo "   cd backend"
echo "   source venv/bin/activate  # or venv\\Scripts\\activate on Windows"
echo "   python main.py"
echo ""
echo "2. Open VS Code and press F5 to start the extension"
echo ""
echo "3. (Optional) Install Ollama and pull a model:"
echo "   ollama pull codellama"
echo ""
echo "4. (Optional) Train the refactoring model:"
echo "   cd models"
echo "   python train_refactoring_ppo.py --sample-data --epochs 3"
echo ""
echo "For more information, see README.md"
echo ""
