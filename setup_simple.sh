#!/bin/bash
# Simple setup using system Python packages

echo "Installing system packages with GTK 4 support..."

sudo apt update
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    python3-pil \
    python3-reportlab \
    python3-pip

echo ""
echo "System packages installed!"
echo ""
echo "You can now run the application with system Python:"
echo "  python3 main.py"
echo ""
echo "Note: Using system Python packages instead of virtual environment for GTK compatibility"
