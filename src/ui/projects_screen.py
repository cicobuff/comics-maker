import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio
from pathlib import Path
from ..models.project import Project


class ProjectsScreen(Gtk.Window):
    """Projects management screen."""
    
    def __init__(self, config, on_project_selected_callback):
        super().__init__(title="Comics Maker - Projects")
        self.config = config
        self.on_project_selected_callback = on_project_selected_callback
        
        self.set_default_size(800, 600)
        
        self._build_ui()
        self._load_projects()
    
    def _build_ui(self):
        """Build the projects UI."""
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        
        new_btn = Gtk.Button(label="New Project")
        new_btn.connect("clicked", self._on_new_project)
        header.pack_start(new_btn)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-activated", self._on_row_activated)
        scrolled.set_child(self.list_box)
        
        box.append(scrolled)
        
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        open_btn = Gtk.Button(label="Open")
        open_btn.add_css_class("suggested-action")
        open_btn.connect("clicked", self._on_open_project)
        button_box.append(open_btn)
        
        delete_btn = Gtk.Button(label="Delete")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._on_delete_project)
        button_box.append(delete_btn)
        
        box.append(button_box)
        
        self.set_child(box)
    
    def _load_projects(self):
        """Load and display available projects."""
        projects_dir = Path(self.config.get("projects_directory"))
        if not projects_dir.exists():
            return
        
        while (child := self.list_box.get_first_child()):
            self.list_box.remove(child)
        
        for project_folder in projects_dir.glob("*.comicmaker"):
            if (project_folder / "project.comic").exists():
                row = Gtk.ListBoxRow()
                label = Gtk.Label(label=project_folder.stem, xalign=0)
                label.set_margin_top(10)
                label.set_margin_bottom(10)
                label.set_margin_start(10)
                label.set_margin_end(10)
                row.set_child(label)
                row.project_path = project_folder
                self.list_box.append(row)
    
    def _on_new_project(self, button):
        """Create a new project."""
        dialog = Gtk.Dialog(title="New Project", transient_for=self)
        dialog.set_modal(True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Create", Gtk.ResponseType.OK)
        
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        
        label = Gtk.Label(label="Project Name:")
        box.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("My Comic")
        box.append(entry)
        
        dialog.connect("response", lambda d, r: self._on_new_project_response(d, r, entry))
        dialog.present()
    
    def _on_new_project_response(self, dialog, response, entry):
        """Handle new project dialog response."""
        if response == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                projects_dir = Path(self.config.get("projects_directory"))
                project = Project.create_new(name, projects_dir)
                self._load_projects()
                
                if self.on_project_selected_callback:
                    self.on_project_selected_callback(project)
                    self.hide()
        
        dialog.close()
    
    def _on_open_project(self, button):
        """Open selected project."""
        selected = self.list_box.get_selected_row()
        if selected:
            project = Project.load(selected.project_path)
            if self.on_project_selected_callback:
                self.on_project_selected_callback(project)
                self.hide()
    
    def _on_row_activated(self, list_box, row):
        """Handle row double-click."""
        project = Project.load(row.project_path)
        if self.on_project_selected_callback:
            self.on_project_selected_callback(project)
            self.hide()
    
    def _on_delete_project(self, button):
        """Delete selected project."""
        selected = self.list_box.get_selected_row()
        if not selected:
            return
        
        dialog = Gtk.AlertDialog()
        dialog.set_message("Delete Project?")
        dialog.set_detail(f"Are you sure you want to delete '{selected.project_path.stem}'?")
        dialog.set_buttons(["Cancel", "Delete"])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        dialog.choose(self, None, self._on_delete_confirm, selected.project_path)
    
    def _on_delete_confirm(self, dialog, result, project_path):
        """Handle delete confirmation."""
        try:
            button = dialog.choose_finish(result)
            if button == 1:
                import shutil
                shutil.rmtree(project_path)
                self._load_projects()
        except Exception as e:
            print(f"Error deleting project: {e}")
