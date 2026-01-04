import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, Gdk
from ..models.project import Project
from ..models.element import Element, ElementType
from ..core.undo_manager import UndoManager


class WorkspaceWindow(Gtk.ApplicationWindow):
    """Main project workspace window."""
    
    def __init__(self, application, project: Project, config, show_projects_callback=None, on_close_callback=None):
        super().__init__(application=application)
        self.project = project
        self.config = config
        self.show_projects_callback = show_projects_callback
        self.on_close_callback = on_close_callback
        self.undo_manager = UndoManager(config.get("undo_limit", 999))
        self.current_page = None
        self.selected_elements = []
        self.zoom_level = 100
        self.grid_visible = False
        
        # Element manipulation state
        self.dragging_element = None
        self.resizing_element = None
        self.resize_handle = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.element_start_x = 0
        self.element_start_y = 0
        self.element_start_width = 0
        self.element_start_height = 0
        
        self.set_title(f"Comics Maker - {project.name}")
        self.set_default_size(1400, 900)
        
        # Connect to close request signal
        self.connect("close-request", self._on_close_request)
        
        # Add key controller at window level for Ctrl+ and Ctrl- shortcuts
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)
        
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
        
        # Make canvas focusable so it can receive keyboard events
        self.canvas.set_can_focus(True)
        self.canvas.set_focusable(True)
        
        # Add scroll controller for zoom
        scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_controller.connect("scroll", self._on_canvas_scroll)
        self.canvas.add_controller(scroll_controller)
        
        # Add drop target for drag and drop
        drop_target = Gtk.DropTarget.new(type=str, actions=Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_canvas_drop)
        self.canvas.add_controller(drop_target)
        
        # Add gesture click for element selection
        gesture_click = Gtk.GestureClick.new()
        gesture_click.connect("pressed", self._on_canvas_click)
        self.canvas.add_controller(gesture_click)
        
        # Add gesture drag for moving/resizing elements
        gesture_drag = Gtk.GestureDrag.new()
        gesture_drag.connect("drag-begin", self._on_drag_begin)
        gesture_drag.connect("drag-update", self._on_drag_update)
        gesture_drag.connect("drag-end", self._on_drag_end)
        self.canvas.add_controller(gesture_drag)
        
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
        
        # Comic Panel button
        panel_btn = self._create_draggable_button("Comic Panel", "panel")
        elements_box.append(panel_btn)
        
        shape_label = Gtk.Label(label="Shapes", xalign=0)
        shape_label.add_css_class("heading")
        elements_box.append(shape_label)
        
        # Shape buttons
        for shape in ["Rectangle", "Circle", "Square", "Triangle", "Pentagon"]:
            btn = self._create_draggable_button(shape, f"shape:{shape.lower()}")
            elements_box.append(btn)
        
        text_label = Gtk.Label(label="Text", xalign=0)
        text_label.add_css_class("heading")
        elements_box.append(text_label)
        
        # Text Area button
        textarea_btn = self._create_draggable_button("Text Area", "textarea")
        elements_box.append(textarea_btn)
        
        bubble_label = Gtk.Label(label="Speech Bubbles", xalign=0)
        bubble_label.add_css_class("heading")
        elements_box.append(bubble_label)
        
        # Speech bubble buttons
        round_bubble_btn = self._create_draggable_button("Round Bubble", "speech_bubble:round")
        elements_box.append(round_bubble_btn)
        
        thought_bubble_btn = self._create_draggable_button("Thought Bubble", "speech_bubble:thought")
        elements_box.append(thought_bubble_btn)
        
        scrolled.set_child(elements_box)
        box.append(scrolled)
        
        return box
    
    def _create_draggable_button(self, label, element_type):
        """Create a button that can be dragged to the canvas."""
        from gi.repository import Gdk
        
        btn = Gtk.Button(label=label)
        
        # Make button a drag source
        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.COPY)
        drag_source.connect("prepare", self._on_drag_prepare, element_type)
        btn.add_controller(drag_source)
        
        return btn
    
    def _on_drag_prepare(self, source, x, y, element_type):
        """Prepare drag data."""
        from gi.repository import Gdk
        
        # Create content provider with the element type
        content = Gdk.ContentProvider.new_for_value(element_type)
        return content
    
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
            
            # Draw page background
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle(x_offset, y_offset, page_width, page_height)
            cr.fill()
            
            # Draw page border
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(1)
            cr.rectangle(x_offset, y_offset, page_width, page_height)
            cr.stroke()
            
            # Draw elements
            for element in self.current_page.elements:
                self._draw_element(cr, element, x_offset, y_offset, scale)
    
    def _draw_element(self, cr, element, page_x, page_y, scale):
        """Draw a single element on the canvas."""
        x = page_x + (element.x * scale)
        y = page_y + (element.y * scale)
        w = element.width * scale
        h = element.height * scale
        
        # Draw based on element type
        if element.type == ElementType.PANEL:
            # Draw comic panel as a rectangle with border
            border_color = element.properties.get("border_color", "#000000")
            bg_color = element.properties.get("background_color", "#FFFFFF")
            
            # Fill with white background first
            bg_r, bg_g, bg_b = self._hex_to_rgb(bg_color)
            cr.set_source_rgb(bg_r, bg_g, bg_b)
            cr.rectangle(x, y, w, h)
            cr.fill()
            
            # Draw grey dithered dot pattern
            cr.set_source_rgb(0.85, 0.85, 0.85)  # Light grey
            dot_spacing = 8  # pixels between dots
            dot_size = 2  # size of each dot
            
            # Draw dots in a grid pattern
            start_x = int(x / dot_spacing) * dot_spacing
            start_y = int(y / dot_spacing) * dot_spacing
            
            current_y = start_y
            while current_y < y + h:
                current_x = start_x
                # Alternate rows for dithered effect
                offset = dot_spacing / 2 if int((current_y - start_y) / dot_spacing) % 2 else 0
                current_x += offset
                
                while current_x < x + w:
                    # Only draw dot if it's within the panel bounds
                    if current_x >= x and current_x <= x + w and current_y >= y and current_y <= y + h:
                        cr.arc(current_x, current_y, dot_size / 2, 0, 2 * 3.14159)
                        cr.fill()
                    current_x += dot_spacing
                current_y += dot_spacing
            
            # Draw border
            border_r, border_g, border_b = self._hex_to_rgb(border_color)
            cr.set_source_rgb(border_r, border_g, border_b)
            cr.set_line_width(2)
            cr.rectangle(x, y, w, h)
            cr.stroke()
        
        elif element.type == ElementType.SHAPE:
            # Draw shapes
            shape_type = element.properties.get("shape_type", "rectangle")
            line_color = element.properties.get("line_color", "#000000")
            bg_color = element.properties.get("background_color", "#FFFFFF")
            
            bg_r, bg_g, bg_b = self._hex_to_rgb(bg_color)
            line_r, line_g, line_b = self._hex_to_rgb(line_color)
            
            if shape_type == "rectangle" or shape_type == "square":
                cr.set_source_rgb(bg_r, bg_g, bg_b)
                cr.rectangle(x, y, w, h)
                cr.fill()
                cr.set_source_rgb(line_r, line_g, line_b)
                cr.set_line_width(2)
                cr.rectangle(x, y, w, h)
                cr.stroke()
            elif shape_type == "circle":
                import math
                radius = min(w, h) / 2
                center_x = x + w / 2
                center_y = y + h / 2
                cr.set_source_rgb(bg_r, bg_g, bg_b)
                cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgb(line_r, line_g, line_b)
                cr.set_line_width(2)
                cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
                cr.stroke()
        
        elif element.type == ElementType.TEXTAREA:
            # Draw text area
            bg_r, bg_g, bg_b = self._hex_to_rgb(element.properties.get("background_color", "#FFFFFF"))
            cr.set_source_rgb(bg_r, bg_g, bg_b)
            cr.rectangle(x, y, w, h)
            cr.fill()
            
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(1)
            cr.rectangle(x, y, w, h)
            cr.stroke()
            
            # Draw placeholder text
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.move_to(x + 5, y + 15)
            cr.show_text(element.properties.get("text", "Enter text here"))
        
        # Draw selection if selected
        if element in self.selected_elements:
            selection_color = self.config.get("selection_color", "#0066FF")
            sel_r, sel_g, sel_b = self._hex_to_rgb(selection_color)
            cr.set_source_rgb(sel_r, sel_g, sel_b)
            cr.set_line_width(2)
            cr.set_dash([5, 5])
            cr.rectangle(x, y, w, h)
            cr.stroke()
            cr.set_dash([])
            
            # Draw resize handles
            handle_size = 8
            handles = [
                (x - handle_size/2, y - handle_size/2),  # Top-left
                (x + w - handle_size/2, y - handle_size/2),  # Top-right
                (x - handle_size/2, y + h - handle_size/2),  # Bottom-left
                (x + w - handle_size/2, y + h - handle_size/2),  # Bottom-right
            ]
            cr.set_source_rgb(sel_r, sel_g, sel_b)
            for hx, hy in handles:
                cr.rectangle(hx, hy, handle_size, handle_size)
                cr.fill()
    
    def _hex_to_rgb(self, hex_color):
        """Convert hex color to RGB tuple (0-1 range)."""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b)
    
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
    
    def _on_canvas_scroll(self, controller, dx, dy):
        """Handle scroll events on canvas for zooming."""
        # Get modifier state to check for Ctrl key
        modifiers = controller.get_current_event_state()
        
        # dy < 0 means scroll up (zoom in), dy > 0 means scroll down (zoom out)
        if dy < 0:
            self._on_zoom_in(None, None)
        else:
            self._on_zoom_out(None, None)
        
        return True
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events for Ctrl+/Ctrl- shortcuts."""
        from gi.repository import Gdk
        
        # Check if Ctrl is pressed
        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK
        
        if ctrl_pressed:
            # Ctrl + = or Ctrl + Plus for zoom in
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self._on_zoom_in(None, None)
                return True
            # Ctrl - or Ctrl Minus for zoom out
            elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self._on_zoom_out(None, None)
                return True
        
        return False
    
    def _on_canvas_drop(self, drop_target, value, x, y):
        """Handle drop event on canvas."""
        if not self.current_page:
            return False
        
        element_type = value
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        canvas_width = self.canvas.get_width()
        canvas_height = self.canvas.get_height()
        
        x_offset = max((canvas_width - page_width) / 2, 0)
        y_offset = max((canvas_height - page_height) / 2, 0)
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        # Check if drop is within page bounds
        if page_x < 0 or page_x > self.current_page.width or page_y < 0 or page_y > self.current_page.height:
            return False
        
        # Create element based on type
        element = self._create_element_from_type(element_type, page_x, page_y)
        if element:
            self.current_page.add_element(element)
            self.canvas.queue_draw()
            return True
        
        return False
    
    def _create_element_from_type(self, element_type, x, y):
        """Create an element from a type string."""
        if element_type == "panel":
            # Create comic panel (20% of page size)
            width = self.current_page.width * 0.2
            height = self.current_page.height * 0.2
            return Element(
                ElementType.PANEL,
                x, y, width, height,
                border_color=self.config.get("panel_border_color", "#000000"),
                border_width=self.config.get("panel_border_width", 2),
                background_color="#FFFFFF"
            )
        
        elif element_type.startswith("shape:"):
            shape_name = element_type.split(":")[1]
            return Element(
                ElementType.SHAPE,
                x, y, 150, 150,
                shape_type=shape_name,
                line_color="#000000",
                line_weight=2,
                background_color="#FFFFFF"
            )
        
        elif element_type == "textarea":
            return Element(
                ElementType.TEXTAREA,
                x, y, 200, 100,
                text="Enter text here",
                font="Arial",
                text_color="#000000",
                background_color="#FFFFFF"
            )
        
        elif element_type.startswith("speech_bubble:"):
            bubble_type = element_type.split(":")[1]
            return Element(
                ElementType.SPEECH_BUBBLE,
                x, y, 200, 100,
                bubble_type=bubble_type,
                text="Enter text here",
                font="Arial",
                text_color="#000000",
                background_color="#FFFFFF"
            )
        
        return None
    
    def _on_canvas_click(self, gesture, n_press, x, y):
        """Handle click on canvas for element selection."""
        if not self.current_page:
            return
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        canvas_width = self.canvas.get_width()
        canvas_height = self.canvas.get_height()
        
        x_offset = max((canvas_width - page_width) / 2, 0)
        y_offset = max((canvas_height - page_height) / 2, 0)
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        # Find clicked element (top to bottom)
        clicked_element = None
        for element in reversed(self.current_page.elements):
            if (element.x <= page_x <= element.x + element.width and
                element.y <= page_y <= element.y + element.height):
                clicked_element = element
                break
        
        # Update selection
        if clicked_element:
            self.selected_elements = [clicked_element]
        else:
            self.selected_elements = []
        
        self.canvas.queue_draw()
    
    def _on_drag_begin(self, gesture, start_x, start_y):
        """Handle drag begin for moving/resizing elements."""
        if not self.current_page or not self.selected_elements:
            return
        
        element = self.selected_elements[0]
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        canvas_width = self.canvas.get_width()
        canvas_height = self.canvas.get_height()
        
        x_offset = max((canvas_width - page_width) / 2, 0)
        y_offset = max((canvas_height - page_height) / 2, 0)
        
        # Convert canvas coordinates to page coordinates
        page_x = (start_x - x_offset) / scale
        page_y = (start_y - y_offset) / scale
        
        # Check if clicking on a resize handle
        handle_size = 8 / scale
        handles = {
            'top-left': (element.x, element.y),
            'top-right': (element.x + element.width, element.y),
            'bottom-left': (element.x, element.y + element.height),
            'bottom-right': (element.x + element.width, element.y + element.height),
        }
        
        for handle_name, (hx, hy) in handles.items():
            if (hx - handle_size <= page_x <= hx + handle_size and
                hy - handle_size <= page_y <= hy + handle_size):
                self.resizing_element = element
                self.resize_handle = handle_name
                self.drag_start_x = page_x
                self.drag_start_y = page_y
                self.element_start_x = element.x
                self.element_start_y = element.y
                self.element_start_width = element.width
                self.element_start_height = element.height
                return
        
        # If not on a handle, start dragging the element
        if (element.x <= page_x <= element.x + element.width and
            element.y <= page_y <= element.y + element.height):
            self.dragging_element = element
            self.drag_start_x = page_x
            self.drag_start_y = page_y
            self.element_start_x = element.x
            self.element_start_y = element.y
    
    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Handle drag update for moving/resizing elements."""
        scale = self.zoom_level / 100.0
        
        # Convert offset from canvas to page coordinates
        dx = offset_x / scale
        dy = offset_y / scale
        
        if self.dragging_element:
            # Move the element
            self.dragging_element.x = self.element_start_x + dx
            self.dragging_element.y = self.element_start_y + dy
            
            # Constrain to page bounds
            if self.dragging_element.x < 0:
                self.dragging_element.x = 0
            if self.dragging_element.y < 0:
                self.dragging_element.y = 0
            if self.dragging_element.x + self.dragging_element.width > self.current_page.width:
                self.dragging_element.x = self.current_page.width - self.dragging_element.width
            if self.dragging_element.y + self.dragging_element.height > self.current_page.height:
                self.dragging_element.y = self.current_page.height - self.dragging_element.height
            
            self.canvas.queue_draw()
        
        elif self.resizing_element:
            # Resize the element based on which handle is being dragged
            element = self.resizing_element
            
            if self.resize_handle == 'top-left':
                new_x = self.element_start_x + dx
                new_y = self.element_start_y + dy
                new_width = self.element_start_width - dx
                new_height = self.element_start_height - dy
                
                if new_width > 20 and new_height > 20:
                    element.x = new_x
                    element.y = new_y
                    element.width = new_width
                    element.height = new_height
            
            elif self.resize_handle == 'top-right':
                new_y = self.element_start_y + dy
                new_width = self.element_start_width + dx
                new_height = self.element_start_height - dy
                
                if new_width > 20 and new_height > 20:
                    element.y = new_y
                    element.width = new_width
                    element.height = new_height
            
            elif self.resize_handle == 'bottom-left':
                new_x = self.element_start_x + dx
                new_width = self.element_start_width - dx
                new_height = self.element_start_height + dy
                
                if new_width > 20 and new_height > 20:
                    element.x = new_x
                    element.width = new_width
                    element.height = new_height
            
            elif self.resize_handle == 'bottom-right':
                new_width = self.element_start_width + dx
                new_height = self.element_start_height + dy
                
                if new_width > 20 and new_height > 20:
                    element.width = new_width
                    element.height = new_height
            
            self.canvas.queue_draw()
    
    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle drag end."""
        self.dragging_element = None
        self.resizing_element = None
        self.resize_handle = None
    
    def _on_close_request(self, window):
        """Handle window close request."""
        if self.on_close_callback:
            self.on_close_callback(self)
        return False
