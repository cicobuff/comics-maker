import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from pathlib import Path


class SetupScreen(Gtk.Window):
    """Initial setup screen for first-time configuration."""
    
    def __init__(self, config, on_complete_callback):
        super().__init__(title="Comics Maker - Initial Setup")
        self.config = config
        self.on_complete_callback = on_complete_callback
        
        self.set_default_size(600, 300)
        self.set_resizable(False)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the setup UI."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        
        title = Gtk.Label(label="Welcome to Comics Maker")
        title.add_css_class("title-1")
        box.append(title)
        
        subtitle = Gtk.Label(label="Please configure your settings")
        subtitle.add_css_class("dim-label")
        box.append(subtitle)
        
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_margin_top(20)
        
        label1 = Gtk.Label(label="Settings Directory:", xalign=0)
        grid.attach(label1, 0, 0, 1, 1)
        
        self.settings_entry = Gtk.Entry()
        self.settings_entry.set_text(self.config.get("settings_directory"))
        self.settings_entry.set_hexpand(True)
        grid.attach(self.settings_entry, 1, 0, 1, 1)
        
        browse_btn1 = Gtk.Button(label="Browse...")
        browse_btn1.connect("clicked", self._on_browse_settings)
        grid.attach(browse_btn1, 2, 0, 1, 1)
        
        label2 = Gtk.Label(label="Projects Directory:", xalign=0)
        grid.attach(label2, 0, 1, 1, 1)
        
        self.projects_entry = Gtk.Entry()
        self.projects_entry.set_text(self.config.get("projects_directory"))
        self.projects_entry.set_hexpand(True)
        grid.attach(self.projects_entry, 1, 1, 1, 1)
        
        browse_btn2 = Gtk.Button(label="Browse...")
        browse_btn2.connect("clicked", self._on_browse_projects)
        grid.attach(browse_btn2, 2, 1, 1, 1)
        
        box.append(grid)
        
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(20)
        
        complete_btn = Gtk.Button(label="Complete Setup")
        complete_btn.add_css_class("suggested-action")
        complete_btn.connect("clicked", self._on_complete)
        button_box.append(complete_btn)
        
        box.append(button_box)
        
        self.set_child(box)
    
    def _on_browse_settings(self, button):
        """Browse for settings directory."""
        dialog = Gtk.FileDialog()
        dialog.select_folder(callback=self._on_settings_folder_selected)
    
    def _on_settings_folder_selected(self, dialog, result):
        """Handle settings folder selection."""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.settings_entry.set_text(folder.get_path())
        except Exception:
            pass
    
    def _on_browse_projects(self, button):
        """Browse for projects directory."""
        dialog = Gtk.FileDialog()
        dialog.select_folder(callback=self._on_projects_folder_selected)
    
    def _on_projects_folder_selected(self, dialog, result):
        """Handle projects folder selection."""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.projects_entry.set_text(folder.get_path())
        except Exception:
            pass
    
    def _on_complete(self, button):
        """Complete setup and save configuration."""
        self.config.set("settings_directory", self.settings_entry.get_text())
        self.config.set("projects_directory", self.projects_entry.get_text())
        self.config.save()
        self.config.ensure_directories()
        
        if self.on_complete_callback:
            self.on_complete_callback()
        
        self.close()
