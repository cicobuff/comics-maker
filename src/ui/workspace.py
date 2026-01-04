import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio
from ..models.project import Project
from ..core.undo_manager import UndoManager


class WorkspaceWindow(Gtk.ApplicationWindow):
    """Main project workspace window."""
    
    def __init__(self, application, project: Project, config, show_projects_callback=None):
        super().__init__(application=application)
        self.project = project
        self.config = config
        self.show_projects_callback = show_projects_callback
        self.undo_manager = UndoManager(config.get("undo_limit", 999))
        self.current_page = None
        self.selected_elements = []
        self.zoom_level = 100
        self.grid_visible = False
        
        self.set_title(f"Comics Maker - {project.name}")
        self.set_default_size(1400, 900)
        
        self._build_ui()
        
        if self.project.pages:
            self.current_page = self.project.pages[0]
    
    def _build_ui(self):
        """Build the workspace UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        self._create_menubar(main_box)
        self._create_toolbar(main_box)
        
        paned_h = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned_h.set_vexpand(True)
        
        self.left_panel = self._create_left_panel()
        paned_h.set_start_child(self.left_panel)
        paned_h.set_resize_start_child(False)
        paned_h.set_shrink_start_child(False)
        
        center_and_right = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        center_and_right.set_position(1000)
        
        self.work_area = self._create_work_area()
        center_and_right.set_start_child(self.work_area)
        
        self.right_panel = self._create_right_panel()
        center_and_right.set_end_child(self.right_panel)
        center_and_right.set_resize_end_child(False)
        center_and_right.set_shrink_end_child(False)
        
        paned_h.set_end_child(center_and_right)
        
        main_box.append(paned_h)
        
        self.set_child(main_box)
    
    def _create_menubar(self, parent_box):
        """Create the menu bar."""
        menu_model = Gio.Menu()
        
        file_menu = Gio.Menu()
        file_menu.append("New Project", "win.new_project")
        file_menu.append("Open", "win.open_project")
        file_menu.append("Save", "win.save")
        file_menu.append("Save As...", "win.save_as")
        file_menu.append("Export", "win.export")
        file_menu.append("Settings", "win.settings")
        file_menu.append("Quit", "win.quit")
        menu_model.append_submenu("File", file_menu)
        
        edit_menu = Gio.Menu()
        edit_menu.append("Undo", "win.undo")
        edit_menu.append("Redo", "win.redo")
        edit_menu.append("Copy", "win.copy")
        edit_menu.append("Paste", "win.paste")
        menu_model.append_submenu("Edit", edit_menu)
        
        view_menu = Gio.Menu()
        view_menu.append("Zoom In", "win.zoom_in")
        view_menu.append("Zoom Out", "win.zoom_out")
        view_menu.append("Full Page", "win.full_page")
        view_menu.append("Page Width", "win.page_width")
        view_menu.append("Toggle Grid", "win.toggle_grid")
        menu_model.append_submenu("View", view_menu)
        
        menu_bar = Gtk.PopoverMenuBar.new_from_model(menu_model)
        parent_box.append(menu_bar)
        
        self._create_actions()
    
    def _create_actions(self):
        """Create window actions."""
        actions = {
            "new_project": self._on_new_project,
            "open_project": self._on_open_project,
            "save": self._on_save,
            "save_as": self._on_save_as,
            "export": self._on_export,
            "settings": self._on_settings,
            "quit": self._on_quit,
            "undo": self._on_undo,
            "redo": self._on_redo,
            "copy": self._on_copy,
            "paste": self._on_paste,
            "zoom_in": self._on_zoom_in,
            "zoom_out": self._on_zoom_out,
            "full_page": self._on_full_page,
            "page_width": self._on_page_width,
            "toggle_grid": self._on_toggle_grid,
        }
        
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
    
    def _create_toolbar(self, parent_box):
        """Create the toolbar."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        toolbar.add_css_class("toolbar")
        toolbar.set_margin_start(5)
        toolbar.set_margin_end(5)
        toolbar.set_margin_top(5)
        toolbar.set_margin_bottom(5)
        
        save_btn = Gtk.Button(label="Save")
        save_btn.connect("clicked", lambda b: self._on_save(None, None))
        toolbar.append(save_btn)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        undo_btn = Gtk.Button(label="Undo")
        undo_btn.connect("clicked", lambda b: self._on_undo(None, None))
        toolbar.append(undo_btn)
        
        redo_btn = Gtk.Button(label="Redo")
        redo_btn.connect("clicked", lambda b: self._on_redo(None, None))
        toolbar.append(redo_btn)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        zoom_out_btn = Gtk.Button(label="-")
        zoom_out_btn.connect("clicked", lambda b: self._on_zoom_out(None, None))
        toolbar.append(zoom_out_btn)
        
        self.zoom_label = Gtk.Label(label="100%")
        toolbar.append(self.zoom_label)
        
        zoom_in_btn = Gtk.Button(label="+")
        zoom_in_btn.connect("clicked", lambda b: self._on_zoom_in(None, None))
        toolbar.append(zoom_in_btn)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        export_btn = Gtk.Button(label="Export")
        export_btn.connect("clicked", lambda b: self._on_export(None, None))
        toolbar.append(export_btn)
        
        parent_box.append(toolbar)
    
    def _create_left_panel(self):
        """Create the left page panel."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.set_size_request(200, -1)
        
        label = Gtk.Label(label="Pages")
        label.add_css_class("heading")
        box.append(label)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        
        self.pages_list = Gtk.ListBox()
        self.pages_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.pages_list.connect("row-selected", self._on_page_selected)
        scrolled.set_child(self.pages_list)
        
        box.append(scrolled)
        
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        add_btn = Gtk.Button(label="Add")
        add_btn.connect("clicked", self._on_add_page)
        btn_box.append(add_btn)
        
        dup_btn = Gtk.Button(label="Duplicate")
        dup_btn.connect("clicked", self._on_duplicate_page)
        btn_box.append(dup_btn)
        
        del_btn = Gtk.Button(label="Delete")
        del_btn.connect("clicked", self._on_delete_page)
        btn_box.append(del_btn)
        
        box.append(btn_box)
        
        self._refresh_pages_list()
        
        return box
    
    def _create_work_area(self):
        """Create the center work area."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_draw_func(self._draw_canvas)
        self.canvas.set_size_request(800, 600)
        
        scrolled.set_child(self.canvas)
        
        return scrolled
    
    def _create_right_panel(self):
        """Create the right elements panel."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.set_size_request(250, -1)
        
        label = Gtk.Label(label="Elements")
        label.add_css_class("heading")
        box.append(label)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        
        elements_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        elements_box.set_margin_start(5)
        elements_box.set_margin_end(5)
        
        panel_btn = Gtk.Button(label="Comic Panel")
        elements_box.append(panel_btn)
        
        shape_label = Gtk.Label(label="Shapes", xalign=0)
        shape_label.add_css_class("heading")
        elements_box.append(shape_label)
        
        for shape in ["Rectangle", "Circle", "Square", "Triangle", "Pentagon"]:
            btn = Gtk.Button(label=shape)
            elements_box.append(btn)
        
        text_label = Gtk.Label(label="Text", xalign=0)
        text_label.add_css_class("heading")
        elements_box.append(text_label)
        
        textarea_btn = Gtk.Button(label="Text Area")
        elements_box.append(textarea_btn)
        
        bubble_label = Gtk.Label(label="Speech Bubbles", xalign=0)
        bubble_label.add_css_class("heading")
        elements_box.append(bubble_label)
        
        round_bubble_btn = Gtk.Button(label="Round Bubble")
        elements_box.append(round_bubble_btn)
        
        thought_bubble_btn = Gtk.Button(label="Thought Bubble")
        elements_box.append(thought_bubble_btn)
        
        scrolled.set_child(elements_box)
        box.append(scrolled)
        
        return box
    
    def _draw_canvas(self, area, cr, width, height):
        """Draw the canvas."""
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.paint()
        
        if self.current_page:
            scale = self.zoom_level / 100.0
            page_width = self.current_page.width * scale
            page_height = self.current_page.height * scale
            
            x_offset = max((width - page_width) / 2, 0)
            y_offset = max((height - page_height) / 2, 0)
            
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle(x_offset, y_offset, page_width, page_height)
            cr.fill()
            
            cr.set_source_rgb(0, 0, 0)
            cr.rectangle(x_offset, y_offset, page_width, page_height)
            cr.stroke()
    
    def _refresh_pages_list(self):
        """Refresh the pages list."""
        while (child := self.pages_list.get_first_child()):
            self.pages_list.remove(child)
        
        for i, page in enumerate(self.project.pages):
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=f"Page {i + 1}", xalign=0)
            label.set_margin_top(5)
            label.set_margin_bottom(5)
            label.set_margin_start(5)
            label.set_margin_end(5)
            row.set_child(label)
            row.page = page
            self.pages_list.append(row)
    
    def _on_page_selected(self, list_box, row):
        """Handle page selection."""
        if row:
            self.current_page = row.page
            self.canvas.queue_draw()
    
    def _on_add_page(self, button):
        """Add a new page."""
        self.project.add_page()
        self._refresh_pages_list()
    
    def _on_duplicate_page(self, button):
        """Duplicate selected page."""
        selected = self.pages_list.get_selected_row()
        if selected:
            self.project.duplicate_page(selected.page)
            self._refresh_pages_list()
    
    def _on_delete_page(self, button):
        """Delete selected page."""
        selected = self.pages_list.get_selected_row()
        if selected and len(self.project.pages) > 1:
            self.project.remove_page(selected.page)
            self._refresh_pages_list()
            if self.project.pages:
                self.current_page = self.project.pages[0]
                self.canvas.queue_draw()
    
    def _on_new_project(self, action, param):
        """Create new project - show projects screen."""
        if self.show_projects_callback:
            self.show_projects_callback()
    
    def _on_open_project(self, action, param):
        """Open project - show projects screen."""
        if self.show_projects_callback:
            self.show_projects_callback()
    
    def _on_save(self, action, param):
        """Save project."""
        self.project.save()
    
    def _on_save_as(self, action, param):
        """Save project as."""
        pass
    
    def _on_export(self, action, param):
        """Export project."""
        pass
    
    def _on_settings(self, action, param):
        """Open settings dialog."""
        pass
    
    def _on_quit(self, action, param):
        """Quit application."""
        self.get_application().quit()
    
    def _on_undo(self, action, param):
        """Undo last action."""
        self.undo_manager.undo()
        self.canvas.queue_draw()
    
    def _on_redo(self, action, param):
        """Redo last action."""
        self.undo_manager.redo()
        self.canvas.queue_draw()
    
    def _on_copy(self, action, param):
        """Copy selected elements."""
        pass
    
    def _on_paste(self, action, param):
        """Paste elements."""
        pass
    
    def _on_zoom_in(self, action, param):
        """Zoom in."""
        max_zoom = self.config.get("max_zoom", 800)
        self.zoom_level = min(self.zoom_level + self.config.get("scroll_zoom_step", 10), max_zoom)
        self.zoom_label.set_text(f"{self.zoom_level}%")
        self.canvas.queue_draw()
    
    def _on_zoom_out(self, action, param):
        """Zoom out."""
        min_zoom = self.config.get("min_zoom", 10)
        self.zoom_level = max(self.zoom_level - self.config.get("scroll_zoom_step", 10), min_zoom)
        self.zoom_label.set_text(f"{self.zoom_level}%")
        self.canvas.queue_draw()
    
    def _on_full_page(self, action, param):
        """Zoom to fit full page."""
        if self.current_page:
            canvas_width = self.canvas.get_width()
            canvas_height = self.canvas.get_height()
            zoom_w = (canvas_width / self.current_page.width) * 100
            zoom_h = (canvas_height / self.current_page.height) * 100
            self.zoom_level = min(zoom_w, zoom_h) * 0.9
            self.zoom_label.set_text(f"{int(self.zoom_level)}%")
            self.canvas.queue_draw()
    
    def _on_page_width(self, action, param):
        """Zoom to fit page width."""
        if self.current_page:
            canvas_width = self.canvas.get_width()
            self.zoom_level = (canvas_width / self.current_page.width) * 100 * 0.9
            self.zoom_label.set_text(f"{int(self.zoom_level)}%")
            self.canvas.queue_draw()
    
    def _on_toggle_grid(self, action, param):
        """Toggle grid visibility."""
        self.grid_visible = not self.grid_visible
        self.canvas.queue_draw()
