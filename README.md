# Comics Maker

A GTK 4 application for creating and exporting comic books.

## Features

- Multi-page comic project management
- Drag and drop image support
- Comic panels, shapes, text areas, and speech bubbles
- Layer management
- Zoom controls
- Undo/Redo support (up to 999 steps)
- Export to PDF and CBZ formats
- Grid and snap-to-grid functionality

## Requirements

- Python 3.12+
- GTK 4.0
- PyGObject
- Cairo
- Pillow
- ReportLab

## Installation

### Option 1: Simple System Packages (Recommended for GTK apps)

GTK 4 applications work best with system Python packages:

```bash
# Install all required system packages
./setup_simple.sh

# Run the application
python3 main.py
```

### Option 2: Virtual Environment (Advanced)

1. Install system dependencies (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    libgirepository1.0-dev \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    gcc \
    g++
```

2. Activate virtual environment (already created):
```bash
source .venv/bin/activate
```

3. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Usage

**Important:** You need to install one more package first:
```bash
sudo apt install python3-reportlab
```

Then run the application using the system Python:
```bash
./run.sh
# or
/usr/bin/python3 main.py
```

**Do NOT use:** `python3 main.py` if you have a venv activated, as it won't find GTK.

On first launch, you'll be prompted to configure:
- Settings directory (default: ~/.comicsmaker)
- Projects directory (default: ~/Documents/ComicsMaker)

### Troubleshooting

If you get errors about missing GTK or GObject modules:
1. Make sure you ran `./setup_simple.sh` to install system packages
2. Use system Python (`python3`) instead of a virtual environment
3. GTK 4 bindings work better with system packages than pip packages

## Project Structure

```
comics-maker/
├── main.py                 # Application entry point
├── src/
│   ├── core/              # Core functionality
│   │   ├── config.py      # Configuration management
│   │   └── undo_manager.py # Undo/redo system
│   ├── models/            # Data models
│   │   ├── element.py     # Element model
│   │   ├── page.py        # Page model
│   │   └── project.py     # Project model
│   └── ui/                # User interface
│       ├── setup_screen.py
│       ├── projects_screen.py
│       └── workspace.py
├── assets/
│   ├── fonts/             # Font files
│   ├── templates/         # Project templates
│   ├── shapes/            # Shape definitions
│   └── speech_bubbles/    # Speech bubble definitions
└── docs/
    └── design.md          # Design specification
```

## Development Status

### Completed
- ✅ Project structure and configuration
- ✅ Data models (Project, Page, Element)
- ✅ Setup screen
- ✅ Projects management screen
- ✅ Main workspace window
- ✅ Menu bar and toolbar
- ✅ Page panel (add, delete, duplicate pages)
- ✅ Basic work area canvas
- ✅ Elements panel
- ✅ Zoom controls
- ✅ Undo/redo system
- ✅ Project save/load

### In Progress
- 🔨 Element rendering (Cairo graphics)
- 🔨 Drag and drop functionality
- 🔨 Element selection and manipulation
- 🔨 Properties panel
- 🔨 Grid and snap-to-grid
- 🔨 Copy/paste/cut
- 🔨 Export to PDF/CBZ

## License

See LICENSE file for details.
