#!/bin/bash
# Install system dependencies for Comics Maker on Ubuntu/Debian

echo "Installing system dependencies..."

sudo apt update
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    libgtk-4-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    gcc \
    g++ \
    cmake \
    meson \
    ninja-build

echo "System dependencies installed successfully!"
echo ""
echo "Checking for girepository-2.0..."
if pkg-config --exists girepository-2.0; then
    echo "✓ girepository-2.0 found"
else
    echo "✗ girepository-2.0 not found"
    echo "Trying additional packages..."
    sudo apt install -y libgirepository-2.0-dev 2>/dev/null || true
fi

echo ""
echo "Now run:"
echo "  source .venv/bin/activate"
echo "  pip install -r requirements.txt"
