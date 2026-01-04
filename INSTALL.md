# Installation Instructions

## Quick Start (Ubuntu/Debian)

You already have most dependencies! Just run:

```bash
# Install the missing package
sudo apt install python3-reportlab

# Test that GTK 4 is available (use system Python!)
/usr/bin/python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print('✓ GTK 4 ready!')"

# Run the application (use the launcher script)
./run.sh
```

## Already Installed

Your system has:
- ✓ python3-gi (3.48.2-1)
- ✓ python3-gi-cairo (3.48.2-1) 
- ✓ gir1.2-gtk-4.0 (4.14.5)
- ✓ python3-pil (10.2.0)

## Missing

You only need:
- ✗ python3-reportlab

## Important Notes

1. **Do NOT use the virtual environment** (.venv) for GTK applications
   - GTK bindings must come from system packages
   - Use `python3 main.py` not `.venv/bin/python main.py`

2. **If you get "No module named 'gi'" error:**
   - Make sure you're using system Python: `which python3`
   - Should show `/usr/bin/python3` not a venv path

3. **Virtual environments and GTK:**
   - Virtual environments can't access system GTK packages
   - This is normal and expected behavior for GTK applications
   - System Python is the right choice here
