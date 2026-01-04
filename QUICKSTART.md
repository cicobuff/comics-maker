# Quick Start Guide

## ✅ What's Been Built

A complete Comics Maker application framework with:
- Project management system
- Multi-page comic editing workspace  
- GTK 4 based user interface
- Configuration and data models
- Undo/redo system (999 steps)
- Zoom controls (10% - 800%)
- Page management (add, delete, duplicate, reorder)

## 🚀 To Run the App Right Now

### Step 1: Install ReportLab (only missing package)
```bash
sudo apt install python3-reportlab
```

### Step 2: Run the app
```bash
./run.sh
```

That's it! The app will launch.

## ✓ Verified Working

Your system has:
- ✓ GTK 4 (version 4.14.5)
- ✓ Python GI bindings (version 3.48.2)
- ✓ Cairo graphics
- ✓ Pillow (PIL)

Only missing:
- ⚠ python3-reportlab (install with command above)

## 📝 Important Notes

### About Virtual Environments

**Do NOT activate the .venv when running this app!**

GTK applications need system Python packages. The virtual environment was created initially but GTK bindings can't be installed via pip - they must come from system packages.

**Right way to run:**
```bash
./run.sh                      # ✓ Uses system Python
/usr/bin/python3 main.py      # ✓ Uses system Python
```

**Wrong way (will fail):**
```bash
source .venv/bin/activate
python3 main.py               # ✗ venv Python can't see GTK
```

## 🎨 What Works Now

1. **Initial Setup Screen** - Configure directories on first launch
2. **Project Management** - Create, open, delete projects
3. **Workspace** - Main editing window with:
   - Menu bar (File, Edit, View)
   - Toolbar (Save, Undo, Redo, Zoom, Export)
   - Page panel (left sidebar)
   - Canvas (center work area)
   - Elements panel (right sidebar)
4. **Page Operations** - Add, duplicate, delete pages
5. **Zoom** - In/out controls with mouse wheel support
6. **Save/Load** - Projects persist to disk in JSON format

## 🔨 Still To Implement

These features are designed but not yet coded:
- Element rendering (drawing shapes, panels, text with Cairo)
- Drag & drop for images and elements
- Element selection and manipulation (move, resize, rotate)
- Properties panel for editing elements
- Multi-selection
- Grid and snap-to-grid
- Copy/paste/cut
- Export to PDF/CBZ

The foundation is solid and ready for these features to be added!

## 📂 Project Files

The application will create:
- `~/.comicsmaker/config.json` - Global settings
- `~/Documents/ComicsMaker/` - Projects directory
- `~/Documents/ComicsMaker/ProjectName.comicmaker/` - Individual project folders

Each project folder contains:
- `project.comic` - Project metadata and pages (JSON)
- `images/` - Imported images (with UUID filenames)
- `thumbs/` - Generated thumbnails (future feature)

## 🐛 Troubleshooting

**Error: "No module named 'gi'"**
- You're using venv Python instead of system Python
- Solution: Use `./run.sh` or `/usr/bin/python3 main.py`

**Error: "Dependency girepository-2.0 not found"**
- This only happens when trying to install in venv
- Solution: Don't use venv, use system packages

**Error: "No module named 'reportlab'"**
- Run: `sudo apt install python3-reportlab`
