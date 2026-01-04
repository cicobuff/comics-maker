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
        self.selection_mode = 'panel'  # 'panel' or 'image' - what's selected in a panel
        self.zoom_level = 100
        self.grid_visible = False
        
        # Page panning state (Shift + Left mouse button)
        self.panning = False
        self.pan_offset_x = 0  # Accumulated pan offset in pixels
        self.pan_offset_y = 0
        self.pan_start_offset_x = 0  # Offset at start of current drag
        self.pan_start_offset_y = 0
        
        # Element manipulation state
        self.dragging_element = None
        self.dragging_image = False  # True if dragging the image inside a panel
        self.dragging_tail = False  # True if dragging speech bubble tail tip
        self.tail_start_x = 0
        self.tail_start_y = 0
        self.resizing_element = None
        self.resizing_image = False  # True if resizing the image inside a panel
        self.resize_handle = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.element_start_x = 0
        self.element_start_y = 0
        self.element_start_width = 0
        self.element_start_height = 0
        self.temp_image_width = 0  # Temporary dimensions during drag
        self.temp_image_height = 0
        self.image_start_offset_x = 0  # For dragging images
        self.image_start_offset_y = 0
        
        # Custom panel edit mode state
        self.edit_mode_element = None  # Element currently in edit mode (custom panel or speech bubble)
        self.selected_vertex = None  # Index of selected vertex for deletion
        self.dragging_vertex = None  # Index of vertex being dragged
        self.vertex_start_x = 0
        self.vertex_start_y = 0
        
        # Speech bubble edit mode state
        self.dragging_bubble_control = None  # Index of control point being dragged
        self.dragging_tail_tip = False  # True if dragging tail tip
        self.dragging_tail_base = False  # True if dragging tail base along curve
        self.tail_base_t_start = 0  # Initial tail_base_t value
        
        # Image cache to avoid reloading images on every frame
        self.image_cache = {}  # key: (filename, width, height), value: cairo surface
        
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
            # Refresh pages list to select the current page
            self._refresh_pages_list()
            # Update canvas size for initial zoom
            self._update_canvas_size()
    
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
        view_menu.append("Center Page", "win.center_page")
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
            "center_page": self._on_center_page,
            "toggle_grid": self._on_toggle_grid,
            "enter_edit_mode": self._on_enter_edit_mode,
            "exit_edit_mode": self._on_exit_edit_mode,
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
        
        center_page_btn = Gtk.Button(label="Center Page")
        center_page_btn.connect("clicked", lambda b: self._on_center_page(None, None))
        toolbar.append(center_page_btn)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        export_btn = Gtk.Button(label="Export")
        export_btn.connect("clicked", lambda b: self._on_export(None, None))
        toolbar.append(export_btn)
        
        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        # Layer ordering buttons
        layer_label = Gtk.Label(label="Layer:")
        toolbar.append(layer_label)
        
        self.bring_front_btn = Gtk.Button(label="⬆⬆")
        self.bring_front_btn.set_tooltip_text("Bring to Front")
        self.bring_front_btn.connect("clicked", self._on_bring_to_front)
        self.bring_front_btn.set_sensitive(False)
        toolbar.append(self.bring_front_btn)
        
        self.bring_forward_btn = Gtk.Button(label="⬆")
        self.bring_forward_btn.set_tooltip_text("Bring Forward")
        self.bring_forward_btn.connect("clicked", self._on_bring_forward)
        self.bring_forward_btn.set_sensitive(False)
        toolbar.append(self.bring_forward_btn)
        
        self.send_backward_btn = Gtk.Button(label="⬇")
        self.send_backward_btn.set_tooltip_text("Send Backward")
        self.send_backward_btn.connect("clicked", self._on_send_backward)
        self.send_backward_btn.set_sensitive(False)
        toolbar.append(self.send_backward_btn)
        
        self.send_back_btn = Gtk.Button(label="⬇⬇")
        self.send_back_btn.set_tooltip_text("Send to Back")
        self.send_back_btn.connect("clicked", self._on_send_to_back)
        self.send_back_btn.set_sensitive(False)
        toolbar.append(self.send_back_btn)
        
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
        
        self.del_page_btn = Gtk.Button(label="Delete")
        self.del_page_btn.connect("clicked", self._on_delete_page)
        btn_box.append(self.del_page_btn)
        
        box.append(btn_box)
        
        self._refresh_pages_list()
        
        return box
    
    def _create_work_area(self):
        """Create the center work area."""
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        
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
        
        # Add drop target for drag and drop (accepts both strings and files)
        # Create a drop target that accepts multiple types
        from gi.repository import GObject
        drop_target = Gtk.DropTarget.new(type=GObject.TYPE_NONE, actions=Gdk.DragAction.COPY)
        drop_target.set_gtypes([str, Gdk.FileList])
        drop_target.connect("drop", self._on_canvas_drop_unified)
        drop_target.connect("accept", self._on_drop_accept)
        self.canvas.add_controller(drop_target)
        
        # Add gesture click for element selection
        gesture_click = Gtk.GestureClick.new()
        gesture_click.connect("pressed", self._on_canvas_click)
        self.canvas.add_controller(gesture_click)
        
        # Add right-click gesture for context menu
        gesture_right_click = Gtk.GestureClick.new()
        gesture_right_click.set_button(3)  # Right button
        gesture_right_click.connect("pressed", self._on_canvas_right_click)
        self.canvas.add_controller(gesture_right_click)
        
        # Add gesture drag for moving/resizing elements
        gesture_drag = Gtk.GestureDrag.new()
        gesture_drag.connect("drag-begin", self._on_drag_begin)
        gesture_drag.connect("drag-update", self._on_drag_update)
        gesture_drag.connect("drag-end", self._on_drag_end)
        self.canvas.add_controller(gesture_drag)
        
        # Add motion controller for cursor changes
        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect("motion", self._on_canvas_motion)
        self.canvas.add_controller(motion_controller)
        
        self.scrolled.set_child(self.canvas)
        
        return self.scrolled
    
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
        
        # Custom Panel button
        custom_panel_btn = self._create_draggable_button("Custom Panel", "custom_panel")
        elements_box.append(custom_panel_btn)
        
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
        """Create a button-like widget that can be dragged to the canvas."""
        from gi.repository import Gdk
        
        # Use a Frame with a Label instead of Button to avoid click event interference
        frame = Gtk.Frame()
        frame.set_margin_top(2)
        frame.set_margin_bottom(2)
        frame.set_margin_start(2)
        frame.set_margin_end(2)
        
        lbl = Gtk.Label(label=label)
        lbl.set_margin_top(6)
        lbl.set_margin_bottom(6)
        lbl.set_margin_start(12)
        lbl.set_margin_end(12)
        frame.set_child(lbl)
        
        # Add CSS class for styling
        frame.add_css_class("draggable-button")
        
        # Make frame a drag source
        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.COPY)
        drag_source.connect("prepare", self._on_drag_prepare, element_type)
        frame.add_controller(drag_source)
        
        return frame
    
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
            
            # Position page at padding offset on the canvas (not centered in viewport)
            padding = 100
            x_offset = padding + self.pan_offset_x
            y_offset = padding + self.pan_offset_y
            
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
            
            # Check if panel has an image
            image_filename = element.properties.get("image")
            
            if image_filename:
                # If image dimensions not stored yet, calculate and store them now
                if "image_width" not in element.properties or "image_height" not in element.properties:
                    from PIL import Image
                    image_path = self.project.images_dir / image_filename
                    if image_path.exists():
                        pil_image = Image.open(str(image_path))
                        img_width, img_height = pil_image.size
                        
                        # Scale to fit within panel while maintaining aspect ratio
                        # Use unscaled panel dimensions for calculations
                        panel_w = element.width
                        panel_h = element.height
                        scale_x = panel_w / img_width
                        scale_y = panel_h / img_height
                        scale_factor = min(scale_x, scale_y)
                        
                        # Store in page coordinates (unscaled)
                        element.properties["image_width"] = img_width * scale_factor
                        element.properties["image_height"] = img_height * scale_factor
                        
                        # Store initial centered offset (relative to panel, in page coordinates)
                        element.properties["image_offset_x"] = (panel_w - img_width * scale_factor) / 2
                        element.properties["image_offset_y"] = (panel_h - img_height * scale_factor) / 2
                
                # Use stored image dimensions (in page coordinates)
                stored_image_width = element.properties.get("image_width", element.width)
                stored_image_height = element.properties.get("image_height", element.height)
                
                # Use stored offset (in page coordinates)
                stored_offset_x = element.properties.get("image_offset_x", (element.width - stored_image_width) / 2)
                stored_offset_y = element.properties.get("image_offset_y", (element.height - stored_image_height) / 2)
                
                # Calculate scaled positions
                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                display_width = stored_image_width * scale
                display_height = stored_image_height * scale
                
                # Get cached surface at original size (not scaled by zoom)
                surface = self._get_cached_image_surface(image_filename, int(stored_image_width), int(stored_image_height))
                
                if surface:
                    # Draw the image with clipping to panel bounds
                    cr.save()
                    # Set clipping region to panel boundaries
                    cr.rectangle(x, y, w, h)
                    cr.clip()
                    
                    # Position and scale the image
                    cr.translate(img_x, img_y)
                    # Scale to desired display size
                    if surface.get_width() > 0 and surface.get_height() > 0:
                        scale_x = display_width / surface.get_width()
                        scale_y = display_height / surface.get_height()
                        cr.scale(scale_x, scale_y)
                    
                    cr.set_source_surface(surface, 0, 0)
                    cr.paint()
                    cr.restore()
                    
                    # If currently resizing this image, draw a preview rectangle at the new size
                    if (self.resizing_image and self.resizing_element == element and 
                        element in self.selected_elements and self.selection_mode == 'image'):
                        preview_x = img_x
                        preview_y = img_y
                        preview_width = self.temp_image_width * scale
                        preview_height = self.temp_image_height * scale
                        
                        # Clip to panel boundaries for preview as well
                        cr.save()
                        cr.rectangle(x, y, w, h)
                        cr.clip()
                        
                        # Draw semi-transparent overlay
                        cr.set_source_rgba(1.0, 0.0, 0.0, 0.2)  # Red with transparency
                        cr.rectangle(preview_x, preview_y, preview_width, preview_height)
                        cr.fill()
                        
                        # Draw solid outline
                        cr.set_source_rgb(1.0, 0.0, 0.0)  # Red
                        cr.set_line_width(3)
                        cr.rectangle(preview_x, preview_y, preview_width, preview_height)
                        cr.stroke()
                        
                        cr.restore()
                else:
                    # Failed to load, show pattern
                    self._draw_panel_pattern(cr, x, y, w, h, bg_color)
            else:
                # No image, draw dithered pattern
                self._draw_panel_pattern(cr, x, y, w, h, bg_color)
            
            # Draw border
            border_r, border_g, border_b = self._hex_to_rgb(border_color)
            cr.set_source_rgb(border_r, border_g, border_b)
            cr.set_line_width(2)
            cr.rectangle(x, y, w, h)
            cr.stroke()
        
        elif element.type == ElementType.CUSTOM_PANEL:
            # Draw custom panel with polygon shape
            vertices = element.properties.get("vertices", [])
            if len(vertices) < 3:
                return  # Need at least 3 vertices
            
            border_color = element.properties.get("border_color", "#000000")
            bg_color = element.properties.get("background_color", "#FFFFFF")
            image_filename = element.properties.get("image")
            
            # Check if panel has an image
            if image_filename:
                # Initialize image dimensions if not set
                if "image_width" not in element.properties or "image_height" not in element.properties:
                    from PIL import Image
                    image_path = self.project.images_dir / image_filename
                    if image_path.exists():
                        pil_image = Image.open(str(image_path))
                        img_width, img_height = pil_image.size
                        
                        # Scale to fit within panel while maintaining aspect ratio
                        panel_w = element.width
                        panel_h = element.height
                        scale_x = panel_w / img_width
                        scale_y = panel_h / img_height
                        scale_factor = min(scale_x, scale_y)
                        
                        # Store in page coordinates (unscaled)
                        element.properties["image_width"] = img_width * scale_factor
                        element.properties["image_height"] = img_height * scale_factor
                        
                        # Store initial centered offset
                        element.properties["image_offset_x"] = (panel_w - img_width * scale_factor) / 2
                        element.properties["image_offset_y"] = (panel_h - img_height * scale_factor) / 2
                
                # Use stored image dimensions
                stored_image_width = element.properties.get("image_width", element.width)
                stored_image_height = element.properties.get("image_height", element.height)
                stored_offset_x = element.properties.get("image_offset_x", 0)
                stored_offset_y = element.properties.get("image_offset_y", 0)
                
                # Calculate scaled positions
                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                display_width = stored_image_width * scale
                display_height = stored_image_height * scale
                
                # Get cached surface
                surface = self._get_cached_image_surface(image_filename, int(stored_image_width), int(stored_image_height))
                
                if surface:
                    # Draw image with clipping to polygon
                    cr.save()
                    # Create polygon clipping path
                    cr.new_path()
                    for i, (vx, vy) in enumerate(vertices):
                        px = x + vx * scale
                        py = y + vy * scale
                        if i == 0:
                            cr.move_to(px, py)
                        else:
                            cr.line_to(px, py)
                    cr.close_path()
                    cr.clip()
                    
                    # Draw image
                    cr.translate(img_x, img_y)
                    if surface.get_width() > 0 and surface.get_height() > 0:
                        scale_x = display_width / surface.get_width()
                        scale_y = display_height / surface.get_height()
                        cr.scale(scale_x, scale_y)
                    cr.set_source_surface(surface, 0, 0)
                    cr.paint()
                    cr.restore()
                else:
                    # Failed to load, show pattern
                    cr.save()
                    cr.new_path()
                    for i, (vx, vy) in enumerate(vertices):
                        px = x + vx * scale
                        py = y + vy * scale
                        if i == 0:
                            cr.move_to(px, py)
                        else:
                            cr.line_to(px, py)
                    cr.close_path()
                    cr.clip_preserve()
                    self._draw_panel_pattern_in_path(cr, x, y, w, h, bg_color, scale)
                    cr.restore()
            else:
                # No image, draw dithered pattern
                cr.save()
                cr.new_path()
                for i, (vx, vy) in enumerate(vertices):
                    px = x + vx * scale
                    py = y + vy * scale
                    if i == 0:
                        cr.move_to(px, py)
                    else:
                        cr.line_to(px, py)
                cr.close_path()
                cr.clip_preserve()
                self._draw_panel_pattern_in_path(cr, x, y, w, h, bg_color, scale)
                cr.restore()
            
            # Draw border
            cr.new_path()
            for i, (vx, vy) in enumerate(vertices):
                px = x + vx * scale
                py = y + vy * scale
                if i == 0:
                    cr.move_to(px, py)
                else:
                    cr.line_to(px, py)
            cr.close_path()
            border_r, border_g, border_b = self._hex_to_rgb(border_color)
            cr.set_source_rgb(border_r, border_g, border_b)
            cr.set_line_width(2)
            cr.stroke()
        
        else:
            # Draw other element types (shapes, text, etc.)
            self._draw_other_elements(cr, element, x, y, w, h, scale)
        
        # Draw selection if selected
        if element in self.selected_elements:
            if self.selection_mode == 'panel':
                # Panel selection - blue dotted line
                selection_color = self.config.get("selection_color", "#0066FF")
                sel_r, sel_g, sel_b = self._hex_to_rgb(selection_color)
                cr.set_source_rgb(sel_r, sel_g, sel_b)
                cr.set_line_width(2)
                cr.set_dash([5, 5])
                cr.rectangle(x, y, w, h)
                cr.stroke()
                cr.set_dash([])
                
                # Draw resize handles for panel
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
            
            elif self.selection_mode == 'image' and (element.type == ElementType.PANEL or element.type == ElementType.CUSTOM_PANEL) and element.properties.get("image"):
                # Image selection - red solid line around the actual image
                stored_image_width = element.properties.get("image_width", element.width)
                stored_image_height = element.properties.get("image_height", element.height)
                
                # Get stored offset
                stored_offset_x = element.properties.get("image_offset_x", (element.width - stored_image_width) / 2)
                stored_offset_y = element.properties.get("image_offset_y", (element.height - stored_image_height) / 2)
                
                # Calculate scaled display dimensions
                if self.resizing_image and self.resizing_element == element:
                    # Use temporary dimensions during resize
                    display_width = self.temp_image_width * scale
                    display_height = self.temp_image_height * scale
                else:
                    display_width = stored_image_width * scale
                    display_height = stored_image_height * scale
                
                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                
                # Red solid line for image
                cr.set_source_rgb(1.0, 0.0, 0.0)  # Red
                cr.set_line_width(2)
                cr.rectangle(img_x, img_y, display_width, display_height)
                cr.stroke()
                
                # Draw resize handles for image
                handle_size = 8
                handles = [
                    (img_x - handle_size/2, img_y - handle_size/2),  # Top-left
                    (img_x + display_width - handle_size/2, img_y - handle_size/2),  # Top-right
                    (img_x - handle_size/2, img_y + display_height - handle_size/2),  # Bottom-left
                    (img_x + display_width - handle_size/2, img_y + display_height - handle_size/2),  # Bottom-right
                ]
                cr.set_source_rgb(1.0, 0.0, 0.0)  # Red
                for hx, hy in handles:
                    cr.rectangle(hx, hy, handle_size, handle_size)
                    cr.fill()
        
        # Draw vertex handles for custom panels in edit mode (not when in image mode)
        if (element.type == ElementType.CUSTOM_PANEL and 
            element == self.edit_mode_element and 
            self.selection_mode != 'image'):
            vertices = element.properties.get("vertices", [])
            handle_size = 8
            cr.set_source_rgb(0.0, 0.8, 0.0)  # Green for vertex handles
            for vx, vy in vertices:
                px = x + vx * scale
                py = y + vy * scale
                cr.arc(px, py, handle_size / 2, 0, 2 * 3.14159)
                cr.fill()
    
    def _get_cached_image_surface(self, image_filename, target_width, target_height):
        """Get or create a cached Cairo surface for an image."""
        cache_key = (image_filename, target_width, target_height)
        
        # Check cache first
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        
        # Load and process the image
        try:
            from PIL import Image
            import cairo
            import array
            
            image_path = self.project.images_dir / image_filename
            if not image_path.exists():
                return None
            
            # Load image with PIL
            pil_image = Image.open(str(image_path))
            
            # Convert to RGBA
            if pil_image.mode != 'RGBA':
                pil_image = pil_image.convert('RGBA')
            
            # Calculate scaling to fit target size while maintaining aspect ratio
            img_width, img_height = pil_image.size
            scale_x = target_width / img_width
            scale_y = target_height / img_height
            scale_factor = min(scale_x, scale_y)
            
            scaled_width = int(img_width * scale_factor)
            scaled_height = int(img_height * scale_factor)
            
            # Resize image
            pil_image = pil_image.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)
            
            # Convert PIL image to Cairo format (ARGB32)
            img_data = pil_image.tobytes('raw', 'RGBA')
            
            # Create array and reorder bytes from RGBA to BGRA
            a = array.array('B', img_data)
            for i in range(0, len(a), 4):
                a[i], a[i+2] = a[i+2], a[i]  # Swap R and B
            
            # Create surface
            surface = cairo.ImageSurface.create_for_data(
                a,
                cairo.FORMAT_ARGB32,
                scaled_width,
                scaled_height
            )
            
            # Cache the surface
            self.image_cache[cache_key] = surface
            
            return surface
            
        except Exception as e:
            print(f"Error loading image {image_filename}: {e}")
            return None
    
    def _draw_panel_pattern(self, cr, x, y, w, h, bg_color):
        """Draw the dithered dot pattern for empty comic panels."""
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
    
    def _draw_panel_pattern_in_path(self, cr, x, y, w, h, bg_color, scale):
        """Draw the dithered dot pattern within the current clipping path."""
        # Fill with background color first (using the preserved clip path)
        bg_r, bg_g, bg_b = self._hex_to_rgb(bg_color)
        cr.set_source_rgb(bg_r, bg_g, bg_b)
        cr.fill_preserve()  # Fill but preserve the clip path
        
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
                # Only draw dot if it's within the bounds
                if current_x >= x and current_x <= x + w and current_y >= y and current_y <= y + h:
                    cr.new_path()  # Start new path for each dot
                    cr.arc(current_x, current_y, dot_size / 2, 0, 2 * 3.14159)
                    cr.fill()
                current_x += dot_spacing
            current_y += dot_spacing
    
    def _draw_other_elements(self, cr, element, x, y, w, h, scale):
        """Draw non-panel elements (shapes, text, etc)."""
        if element.type == ElementType.SHAPE:
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
        
        elif element.type == ElementType.SPEECH_BUBBLE:
            # Draw speech bubble
            import math
            
            # Start with a clean path state
            cr.new_path()
            
            bubble_type = element.properties.get("bubble_type", "round")
            text = element.properties.get("text", "Enter text here")
            text_color = element.properties.get("text_color", "#000000")
            
            # Check if this is the new spline-based round bubble
            control_points = element.properties.get("control_points")
            
            if bubble_type == "round" and control_points:
                # New spline-based round bubble
                # Scale control points to screen coordinates
                scaled_points = [(x + px * w / element.width, y + py * h / element.height) 
                                for px, py in control_points]
                
                # Get tail properties
                tail_base_t = element.properties.get("tail_base_t", 0.75)
                tail_tip_x = element.properties.get("tail_tip_x", w / 2)
                tail_tip_y = element.properties.get("tail_tip_y", h + 50)
                
                # Scale tail tip
                tail_tip_x_scaled = x + (tail_tip_x * w / element.width)
                tail_tip_y_scaled = y + (tail_tip_y * h / element.height)
                
                # Calculate tail base position on curve
                tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)
                tail_base_tangent = self._eval_bubble_curve_tangent_at_t(scaled_points, tail_base_t)
                
                # Calculate perpendicular to tangent for tail width
                tail_width = 30 * scale
                tangent_len = math.sqrt(tail_base_tangent[0]**2 + tail_base_tangent[1]**2)
                if tangent_len > 0:
                    perp_x = -tail_base_tangent[1] / tangent_len * tail_width / 2
                    perp_y = tail_base_tangent[0] / tangent_len * tail_width / 2
                else:
                    perp_x, perp_y = 0, 0
                
                tail_left = (tail_base_pos[0] + perp_x, tail_base_pos[1] + perp_y)
                tail_right = (tail_base_pos[0] - perp_x, tail_base_pos[1] - perp_y)
                
                # Draw tail (behind bubble)
                cr.set_source_rgb(1, 1, 1)  # White fill
                cr.move_to(tail_left[0], tail_left[1])
                cr.line_to(tail_right[0], tail_right[1])
                cr.line_to(tail_tip_x_scaled, tail_tip_y_scaled)
                cr.close_path()
                cr.fill_preserve()
                cr.set_source_rgb(0, 0, 0)  # Black stroke
                cr.set_line_width(2)
                cr.stroke()
                
                # Draw bubble spline curve
                segments = self._get_bubble_curve_segments(scaled_points)
                
                cr.new_path()
                for i, segment in enumerate(segments):
                    p0, p1, p2, p3 = segment
                    if i == 0:
                        cr.move_to(p0[0], p0[1])
                    cr.curve_to(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1])
                
                cr.close_path()
                cr.set_source_rgb(1, 1, 1)  # White fill
                cr.fill_preserve()
                cr.set_source_rgb(0, 0, 0)  # Black stroke
                cr.set_line_width(3)
                cr.stroke()
                
                # Draw text in text area
                text_r, text_g, text_b = self._hex_to_rgb(text_color)
                cr.set_source_rgb(text_r, text_g, text_b)
                
                text_area_x = element.properties.get("text_area_x", 30) * (w / element.width)
                text_area_y = element.properties.get("text_area_y", 30) * (h / element.height)
                font_size = element.properties.get("font_size", 14)
                
                cr.select_font_face(element.properties.get("font", "Arial"))
                cr.set_font_size(font_size)
                cr.move_to(x + text_area_x, y + text_area_y + font_size)
                cr.show_text(text)
                
                # Draw handles if selected
                if element in self.selected_elements:
                    # Bright pink tail handles
                    handle_size = 8
                    
                    # Tail tip handle (bright pink)
                    cr.set_source_rgb(1.0, 0.08, 0.58)  # Hot pink
                    cr.arc(tail_tip_x_scaled, tail_tip_y_scaled, handle_size / 2, 0, 2 * math.pi)
                    cr.fill()
                    
                    # Tail base handle (bright pink)
                    cr.set_source_rgb(1.0, 0.08, 0.58)  # Hot pink
                    cr.arc(tail_base_pos[0], tail_base_pos[1], handle_size / 2, 0, 2 * math.pi)
                    cr.fill()
                    
                    # Control point handles (green) if in edit mode
                    if element == self.edit_mode_element:
                        cr.set_source_rgb(0.0, 0.8, 0.0)  # Green
                        for px, py in scaled_points:
                            cr.arc(px, py, handle_size / 2, 0, 2 * math.pi)
                            cr.fill()
            
            else:
                # Old-style bubble rendering (for bubbles without control_points)
                if bubble_type == "round":
                    # Calculate tail connection points on bubble edge
                    # Find angle from bubble center to tail tip
                    bubble_center_x = x + w / 2
                    bubble_center_y = y + h / 2
                    angle = math.atan2(tail_tip_y_scaled - bubble_center_y, tail_tip_x_scaled - bubble_center_x)
                    
                    # Calculate base points perpendicular to tail direction
                    perp_angle = angle + math.pi / 2
                    base_offset_x = math.cos(perp_angle) * tail_base_width_scaled / 2
                    base_offset_y = math.sin(perp_angle) * tail_base_width_scaled / 2
                    
                    # Find where tail intersects bubble edge (approximate)
                    bubble_rx = w / 2
                    bubble_ry = h / 2
                    edge_dist = math.sqrt((bubble_rx * math.cos(angle))**2 + (bubble_ry * math.sin(angle))**2)
                    edge_x = bubble_center_x + edge_dist * math.cos(angle)
                    edge_y = bubble_center_y + edge_dist * math.sin(angle)
                    
                    # Draw tail triangle
                    cr.set_source_rgb(1, 1, 1)  # White fill
                    cr.move_to(edge_x + base_offset_x, edge_y + base_offset_y)
                    cr.line_to(edge_x - base_offset_x, edge_y - base_offset_y)
                    cr.line_to(tail_tip_x_scaled, tail_tip_y_scaled)
                    cr.close_path()
                    cr.fill_preserve()
                    cr.set_source_rgb(0, 0, 0)  # Black stroke
                    cr.set_line_width(2)
                    cr.stroke()
                
                elif bubble_type == "thought":
                    # Draw thought bubble tail as decreasing circles
                    bubble_center_x = x + w / 2
                    bubble_center_y = y + h / 2
                    
                    # Calculate positions for 3 circles from bubble to tip
                    num_circles = 3
                    for i in range(num_circles):
                        t = (i + 1) / (num_circles + 1)
                        circle_x = bubble_center_x + t * (tail_tip_x_scaled - bubble_center_x)
                        circle_y = bubble_center_y + t * (tail_tip_y_scaled - bubble_center_y)
                        radius = (15 - i * 4) * scale  # Decreasing radius
                        
                        cr.set_source_rgb(1, 1, 1)
                        cr.arc(circle_x, circle_y, radius, 0, 2 * math.pi)
                        cr.fill_preserve()
                        cr.set_source_rgb(0, 0, 0)
                        cr.set_line_width(2)
                        cr.stroke()
                
                # Draw bubble body (ellipse)
                cr.set_source_rgb(1, 1, 1)  # White fill
                cr.save()
                cr.translate(x + w/2, y + h/2)
                cr.scale(w/2, h/2)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.fill()
                
                # Draw bubble outline
                cr.set_source_rgb(0, 0, 0)  # Black stroke
                cr.set_line_width(3)
                cr.save()
                cr.translate(x + w/2, y + h/2)
                cr.scale(w/2, h/2)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()
                
                # Draw text in text area
                text_r, text_g, text_b = self._hex_to_rgb(text_color)
                cr.set_source_rgb(text_r, text_g, text_b)
                
                # Get text area properties
                text_area_x = element.properties.get("text_area_x", 20) * (w / element.width)
                text_area_y = element.properties.get("text_area_y", 20) * (h / element.height)
                font_size = element.properties.get("font_size", 12)
                
                cr.select_font_face(element.properties.get("font", "Arial"))
                cr.set_font_size(font_size)
                cr.move_to(x + text_area_x, y + text_area_y + font_size)
                cr.show_text(text)
                
                # Draw tail tip handle if selected
                if element in self.selected_elements:
                    handle_size = 8
                    cr.set_source_rgb(0.0, 0.8, 0.0)  # Green for tail tip handle
                    cr.arc(tail_tip_x_scaled, tail_tip_y_scaled, handle_size / 2, 0, 2 * math.pi)
                    cr.fill()
    
    def _catmull_rom_to_bezier(self, p0, p1, p2, p3):
        """Convert Catmull-Rom curve segment to cubic Bézier control points."""
        # Catmull-Rom to Bézier conversion
        # Returns: (p1, control1, control2, p2)
        c1x = p1[0] + (p2[0] - p0[0]) / 6.0
        c1y = p1[1] + (p2[1] - p0[1]) / 6.0
        
        c2x = p2[0] - (p3[0] - p1[0]) / 6.0
        c2y = p2[1] - (p3[1] - p1[1]) / 6.0
        
        return (p1, (c1x, c1y), (c2x, c2y), p2)
    
    def _eval_bezier_point(self, p0, p1, p2, p3, t):
        """Evaluate a cubic Bézier curve at parameter t (0 to 1)."""
        # Cubic Bézier formula: B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3
        u = 1 - t
        tt = t * t
        uu = u * u
        uuu = uu * u
        ttt = tt * t
        
        x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
        y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
        
        return (x, y)
    
    def _eval_bezier_tangent(self, p0, p1, p2, p3, t):
        """Evaluate tangent vector at parameter t on a cubic Bézier curve."""
        # Derivative of cubic Bézier
        u = 1 - t
        
        dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
        dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
        
        return (dx, dy)
    
    def _get_bubble_curve_segments(self, control_points):
        """Convert control points to Bézier curve segments for closed spline."""
        # Create a closed Catmull-Rom spline through the control points
        segments = []
        n = len(control_points)
        
        for i in range(n):
            p0 = control_points[(i - 1) % n]
            p1 = control_points[i]
            p2 = control_points[(i + 1) % n]
            p3 = control_points[(i + 2) % n]
            
            bezier = self._catmull_rom_to_bezier(p0, p1, p2, p3)
            segments.append(bezier)
        
        return segments
    
    def _eval_bubble_curve_at_t(self, control_points, t):
        """Evaluate position on the closed bubble curve at global parameter t (0 to 1)."""
        segments = self._get_bubble_curve_segments(control_points)
        n = len(segments)
        
        # t is global parameter around the whole curve
        # Map to segment and local t
        segment_t = t * n
        segment_idx = int(segment_t) % n
        local_t = segment_t - int(segment_t)
        
        segment = segments[segment_idx]
        return self._eval_bezier_point(segment[0], segment[1], segment[2], segment[3], local_t)
    
    def _eval_bubble_curve_tangent_at_t(self, control_points, t):
        """Evaluate tangent at global parameter t on the bubble curve."""
        segments = self._get_bubble_curve_segments(control_points)
        n = len(segments)
        
        segment_t = t * n
        segment_idx = int(segment_t) % n
        local_t = segment_t - int(segment_t)
        
        segment = segments[segment_idx]
        return self._eval_bezier_tangent(segment[0], segment[1], segment[2], segment[3], local_t)
    
    def _find_closest_point_on_curve(self, control_points, target_x, target_y):
        """Find parameter t (0 to 1) for the closest point on curve to target position."""
        import math
        
        # Sample the curve at many points to find closest
        samples = 100
        min_dist = float('inf')
        closest_t = 0
        
        for i in range(samples):
            t = i / samples
            px, py = self._eval_bubble_curve_at_t(control_points, t)
            dist = math.sqrt((px - target_x)**2 + (py - target_y)**2)
            
            if dist < min_dist:
                min_dist = dist
                closest_t = t
        
        # Refine with a finer search around the best sample
        step = 1.0 / samples
        for i in range(10):
            t_start = max(0, closest_t - step)
            t_end = min(1, closest_t + step)
            
            for j in range(10):
                t = t_start + (t_end - t_start) * j / 10
                px, py = self._eval_bubble_curve_at_t(control_points, t)
                dist = math.sqrt((px - target_x)**2 + (py - target_y)**2)
                
                if dist < min_dist:
                    min_dist = dist
                    closest_t = t
            
            step /= 10
        
        return closest_t
    
    def _update_custom_panel_bounds(self, element):
        """Update element x, y, width, height to contain all vertices."""
        if element.type != ElementType.CUSTOM_PANEL:
            return
        
        vertices = element.properties.get("vertices", [])
        if len(vertices) < 3:
            return
        
        # Find bounding box
        min_x = float('inf')
        max_x = float('-inf')
        min_y = float('inf')
        max_y = float('-inf')
        
        for vertex in vertices:
            vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
            min_x = min(min_x, vx)
            max_x = max(max_x, vx)
            min_y = min(min_y, vy)
            max_y = max(max_y, vy)
        
        # Update vertices to be relative to new origin
        new_vertices = []
        for vertex in vertices:
            vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
            new_vertices.append((vx - min_x, vy - min_y))
        
        # Update element position and size
        element.x += min_x
        element.y += min_y
        element.width = max_x - min_x
        element.height = max_y - min_y
        element.properties["vertices"] = new_vertices
    
    def _point_to_segment_distance(self, px, py, x1, y1, x2, y2):
        """Calculate the distance from point (px, py) to line segment (x1, y1)-(x2, y2)."""
        import math
        
        # Vector from start to end of segment
        dx = x2 - x1
        dy = y2 - y1
        
        # If segment is actually a point
        if dx == 0 and dy == 0:
            return math.sqrt((px - x1)**2 + (py - y1)**2)
        
        # Calculate parameter t for projection onto line
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        
        # Find closest point on segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        
        # Return distance to closest point
        return math.sqrt((px - closest_x)**2 + (py - closest_y)**2)
    
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
            
            # Select the row if it's the current page
            if self.current_page and page == self.current_page:
                self.pages_list.select_row(row)
        
        # Disable delete button if only one page
        self.del_page_btn.set_sensitive(len(self.project.pages) > 1)
    
    def _on_page_selected(self, list_box, row):
        """Handle page selection."""
        if row:
            self.current_page = row.page
            self._update_canvas_size()
            self.canvas.queue_draw()
    
    def _on_add_page(self, button):
        """Add a new page."""
        new_page = self.project.add_page()
        self.current_page = new_page
        self._refresh_pages_list()
        self._update_canvas_size()
        self.canvas.queue_draw()
    
    def _on_duplicate_page(self, button):
        """Duplicate selected page."""
        selected = self.pages_list.get_selected_row()
        if selected:
            new_page = self.project.duplicate_page(selected.page)
            self.current_page = new_page
            self._refresh_pages_list()
            self._update_canvas_size()
            self.canvas.queue_draw()
    
    def _on_delete_page(self, button):
        """Delete selected page."""
        selected = self.pages_list.get_selected_row()
        if selected and len(self.project.pages) > 1:
            # Get the index of the page being deleted
            page_index = self.project.pages.index(selected.page)
            self.project.remove_page(selected.page)
            
            # Select the previous page, or the first page if we deleted the first one
            if self.project.pages:
                if page_index > 0:
                    self.current_page = self.project.pages[page_index - 1]
                else:
                    self.current_page = self.project.pages[0]
                self._refresh_pages_list()
                self._update_canvas_size()
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
        self._update_canvas_size()
        self.canvas.queue_draw()
    
    def _on_zoom_out(self, action, param):
        """Zoom out."""
        min_zoom = self.config.get("min_zoom", 10)
        self.zoom_level = max(self.zoom_level - self.config.get("scroll_zoom_step", 10), min_zoom)
        self.zoom_label.set_text(f"{self.zoom_level}%")
        self._update_canvas_size()
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
            self._update_canvas_size()
            self.canvas.queue_draw()
    
    def _on_page_width(self, action, param):
        """Zoom to fit page width."""
        if self.current_page:
            canvas_width = self.canvas.get_width()
            self.zoom_level = (canvas_width / self.current_page.width) * 100 * 0.9
            self.zoom_label.set_text(f"{int(self.zoom_level)}%")
            self._update_canvas_size()
            self.canvas.queue_draw()
    
    def _update_canvas_size(self):
        """Update canvas size based on current zoom level to enable scrolling."""
        if not self.current_page:
            return
        
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        
        # Add padding around the page for better visibility and scrolling
        padding = 100
        canvas_width = page_width + padding * 2
        canvas_height = page_height + padding * 2
        
        # Set canvas size to enable scrolling
        self.canvas.set_size_request(int(canvas_width), int(canvas_height))
    
    def _on_center_page(self, action, param):
        """Center the page in the work area."""
        if not self.current_page:
            return
        
        # Update canvas size for current zoom
        self._update_canvas_size()
        
        # Calculate page dimensions at current zoom
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        padding = 100
        
        # Force a redraw to update the canvas
        self.canvas.queue_draw()
        
        # We need to wait for the canvas to be redrawn and adjustments to update
        # Use idle_add to center after the canvas is updated
        from gi.repository import GLib
        def do_center():
            h_adj = self.scrolled.get_hadjustment()
            v_adj = self.scrolled.get_vadjustment()
            
            # Calculate the page center position
            page_center_x = padding + page_width / 2
            page_center_y = padding + page_height / 2
            
            # Calculate scroll position to center the page
            visible_width = h_adj.get_page_size()
            visible_height = v_adj.get_page_size()
            
            target_h = page_center_x - visible_width / 2
            target_v = page_center_y - visible_height / 2
            
            # Clamp to valid ranges
            target_h = max(h_adj.get_lower(), min(target_h, h_adj.get_upper() - visible_width))
            target_v = max(v_adj.get_lower(), min(target_v, v_adj.get_upper() - visible_height))
            
            # Set scroll positions
            h_adj.set_value(target_h)
            v_adj.set_value(target_v)
            
            return False  # Don't repeat
        
        GLib.idle_add(do_center)
    
    def _on_toggle_grid(self, action, param):
        """Toggle grid visibility."""
        self.grid_visible = not self.grid_visible
        self.canvas.queue_draw()
    
    def _on_enter_edit_mode(self, action, param):
        """Enter edit mode for the selected custom panel or speech bubble."""
        if not self.selected_elements:
            return
        
        element = self.selected_elements[0]
        if element.type == ElementType.CUSTOM_PANEL:
            self.edit_mode_element = element
            self.canvas.queue_draw()
        elif element.type == ElementType.SPEECH_BUBBLE:
            # Only spline-based round bubbles support edit mode
            if (element.properties.get("bubble_type") == "round" and
                element.properties.get("control_points") is not None):
                self.edit_mode_element = element
                self.canvas.queue_draw()
    
    def _on_exit_edit_mode(self, action, param):
        """Exit edit mode for custom panel."""
        self.edit_mode_element = None
        self.canvas.queue_draw()
    
    def _on_canvas_scroll(self, controller, dx, dy):
        """Handle scroll events on canvas for zooming."""
        # Get modifier state to check for Shift key - don't zoom while panning
        modifiers = controller.get_current_event_state()
        
        # Don't handle scroll events while panning
        if self.panning or (modifiers & Gdk.ModifierType.SHIFT_MASK):
            return False
        
        # dy < 0 means scroll up (zoom in), dy > 0 means scroll down (zoom out)
        if dy < 0:
            self._on_zoom_in(None, None)
        else:
            self._on_zoom_out(None, None)
        
        return True
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events for Ctrl+/Ctrl- shortcuts and Delete."""
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
        
        # Delete key to remove selected vertex or selected elements
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
            # Check if we're in edit mode with a selected vertex
            if self.edit_mode_element and self.selected_vertex is not None:
                element = self.edit_mode_element
                if element.type == ElementType.CUSTOM_PANEL:
                    vertices = element.properties.get("vertices", [])
                    # Only remove if we have more than 3 vertices (minimum for a polygon)
                    if len(vertices) > 3:
                        vertices.pop(self.selected_vertex)
                        element.properties["vertices"] = vertices
                        self._update_custom_panel_bounds(element)
                        self.selected_vertex = None
                        self.canvas.queue_draw()
                        return True
            # Otherwise, delete selected elements
            elif self.selected_elements and self.current_page:
                for element in self.selected_elements:
                    self.current_page.elements.remove(element)
                self.selected_elements = []
                self.edit_mode_element = None  # Exit edit mode if deleting element
                self._update_layer_buttons()
                self.canvas.queue_draw()
                return True
        
        return False
    
    def _on_drop_accept(self, drop_target, drop):
        """Check if we accept the drop."""
        # Always accept drops to avoid GTK errors
        return True
    
    def _on_canvas_drop_unified(self, drop_target, value, x, y):
        """Handle unified drop event on canvas (both files and elements)."""
        if not self.current_page:
            return True  # Return True to avoid GTK errors
        
        # Check if it's a file list or a string
        if isinstance(value, Gdk.FileList):
            return self._handle_file_drop(value, x, y)
        elif isinstance(value, str):
            return self._handle_element_drop(value, x, y)
        
        return True  # Always return True to avoid GTK errors
    
    def _handle_element_drop(self, element_type, x, y):
        """Handle element drop (string type)."""
        # Check if the string is actually a file path (starts with / or file://)
        if element_type.startswith('/') or element_type.startswith('file://'):
            # Strip file:// prefix if present and trim whitespace/newlines
            file_path = element_type.replace('file://', '').strip()
            
            # Check if it's an image file
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
            if any(file_path.lower().endswith(ext) for ext in valid_extensions):
                return self._handle_file_drop_from_path(file_path, x, y)
        
        # Otherwise, handle as element type
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        # Use padding + pan_offset for coordinate transformation (same as draw function)
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        # Check if drop is within page bounds
        if page_x < 0 or page_x > self.current_page.width or page_y < 0 or page_y > self.current_page.height:
            return True  # Return True to avoid GTK errors
        
        # Create element based on type
        element = self._create_element_from_type(element_type, page_x, page_y)
        if element:
            self.current_page.add_element(element)
            self.canvas.queue_draw()
        
        return True  # Always return True to avoid GTK errors
    
    def _handle_file_drop(self, files, x, y):
        """Handle file drop event on canvas (from Gdk.FileList)."""
        if not files or len(files) == 0:
            return True  # Return True to avoid GTK errors
        
        # Only handle the first file
        file = files[0]
        file_path = file.get_path()
        
        return self._handle_file_drop_from_path(file_path, x, y)
    
    def _handle_file_drop_from_path(self, file_path, x, y):
        """Handle file drop given a file path string."""
        # Check if it's an image file
        valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
        if not any(file_path.lower().endswith(ext) for ext in valid_extensions):
            return True  # Return True to avoid GTK errors
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        # Use padding + pan_offset for coordinate transformation (same as draw function)
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        # Check if drop is within page bounds
        if page_x < 0 or page_x > self.current_page.width or page_y < 0 or page_y > self.current_page.height:
            return True  # Return True to avoid GTK errors
        
        # Copy image to project
        from pathlib import Path
        image_filename = self.project.copy_image_to_project(Path(file_path))
        
        # Check if dropped on an existing panel
        target_panel = None
        for element in reversed(self.current_page.elements):
            if ((element.type == ElementType.PANEL or element.type == ElementType.CUSTOM_PANEL) and
                element.x <= page_x <= element.x + element.width and
                element.y <= page_y <= element.y + element.height):
                target_panel = element
                break
        
        if target_panel:
            # Add image to existing panel (replace if exists)
            target_panel.properties["image"] = image_filename
            
            # Store the image's actual dimensions so it doesn't resize with the panel
            from PIL import Image
            image_path = self.project.images_dir / image_filename
            if image_path.exists():
                pil_image = Image.open(str(image_path))
                img_width, img_height = pil_image.size
                
                # Scale to fit within panel while maintaining aspect ratio
                panel_w = target_panel.width
                panel_h = target_panel.height
                scale_x = panel_w / img_width
                scale_y = panel_h / img_height
                scale_factor = min(scale_x, scale_y)
                
                scaled_width = img_width * scale_factor
                scaled_height = img_height * scale_factor
                
                target_panel.properties["image_width"] = scaled_width
                target_panel.properties["image_height"] = scaled_height
                
                # Store centered offset (relative to panel)
                target_panel.properties["image_offset_x"] = (panel_w - scaled_width) / 2
                target_panel.properties["image_offset_y"] = (panel_h - scaled_height) / 2
        else:
            # Create new panel with image at drop location (20% of page size)
            width = self.current_page.width * 0.2
            height = self.current_page.height * 0.2
            
            # Center panel at drop location
            panel_x = page_x - width / 2
            panel_y = page_y - height / 2
            
            # Constrain to page bounds
            if panel_x < 0:
                panel_x = 0
            if panel_y < 0:
                panel_y = 0
            if panel_x + width > self.current_page.width:
                panel_x = self.current_page.width - width
            if panel_y + height > self.current_page.height:
                panel_y = self.current_page.height - height
            
            panel = Element(
                ElementType.PANEL,
                panel_x, panel_y, width, height,
                border_color=self.config.get("panel_border_color", "#000000"),
                border_width=self.config.get("panel_border_width", 2),
                background_color="#FFFFFF",
                image=image_filename
            )
            
            # Store the image's actual dimensions so it doesn't resize with the panel
            from PIL import Image
            image_path = self.project.images_dir / image_filename
            if image_path.exists():
                pil_image = Image.open(str(image_path))
                img_width, img_height = pil_image.size
                
                # Scale to fit within panel while maintaining aspect ratio
                scale_x = width / img_width
                scale_y = height / img_height
                scale_factor = min(scale_x, scale_y)
                
                scaled_width = img_width * scale_factor
                scaled_height = img_height * scale_factor
                
                panel.properties["image_width"] = scaled_width
                panel.properties["image_height"] = scaled_height
                
                # Store centered offset (relative to panel)
                panel.properties["image_offset_x"] = (width - scaled_width) / 2
                panel.properties["image_offset_y"] = (height - scaled_height) / 2
            
            self.current_page.add_element(panel)
        
        self.canvas.queue_draw()
        return True
    
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
        
        elif element_type == "custom_panel":
            # Create custom panel with 4 corner vertices (20% of page size)
            width = self.current_page.width * 0.2
            height = self.current_page.height * 0.2
            # Vertices stored as list of (x, y) tuples relative to element origin
            vertices = [
                (0, 0),              # top-left
                (width, 0),          # top-right
                (width, height),     # bottom-right
                (0, height)          # bottom-left
            ]
            return Element(
                ElementType.CUSTOM_PANEL,
                x, y, width, height,
                vertices=vertices,
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
            
            if bubble_type == "round":
                # New spline-based round bubble
                import math
                width = 200
                height = 150
                
                # Create 4 control points for a circular bubble
                # Points are placed to form a circle using the width and height as bounding box
                cx = width / 2  # center x
                cy = height / 2  # center y
                rx = width / 2  # radius x
                ry = height / 2  # radius y
                
                # 4 control points at top, right, bottom, left (relative to element origin)
                control_points = [
                    (cx, 0),              # top
                    (width, cy),          # right
                    (cx, height),         # bottom
                    (0, cy)               # left
                ]
                
                # Tail properties
                # tail_base_t: parameter along curve (0.0 to 1.0), 0.75 = bottom position
                tail_base_t = 0.75  # Start at bottom
                # tail_tip: free-moving point (relative to element origin)
                tail_tip_x = cx - 30
                tail_tip_y = height + 50
                
                # Text area (centered in bubble)
                text_area_x = 30
                text_area_y = 30
                text_area_width = width - 60
                text_area_height = height - 60
                
                return Element(
                    ElementType.SPEECH_BUBBLE,
                    x, y, width, height,
                    bubble_type="round",
                    control_points=control_points,
                    tail_base_t=tail_base_t,
                    tail_tip_x=tail_tip_x,
                    tail_tip_y=tail_tip_y,
                    text="Enter text here",
                    font="Arial",
                    font_size=14,
                    text_color="#000000",
                    text_align="center",
                    vertical_align="middle",
                    text_area_x=text_area_x,
                    text_area_y=text_area_y,
                    text_area_width=text_area_width,
                    text_area_height=text_area_height
                )
            else:
                # Fallback for other bubble types (thought bubble, etc.)
                return Element(
                    ElementType.SPEECH_BUBBLE,
                    x, y, 200, 150,
                    bubble_type=bubble_type,
                    text="Enter text here",
                    font="Arial",
                    font_size=12,
                    text_color="#000000",
                    tail_tip_x=70,
                    tail_tip_y=200,
                    tail_base_width=30
                )
        
        return None
    
    def _on_canvas_click(self, gesture, n_press, x, y):
        """Handle click on canvas for element selection."""
        if not self.current_page:
            return
        
        # Check for Ctrl modifier for adding vertices
        event = gesture.get_current_event()
        modifiers = event.get_modifier_state()
        ctrl_pressed = modifiers & Gdk.ModifierType.CONTROL_MASK
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        # Use padding + pan_offset for coordinate transformation (same as draw function)
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        # Handle Ctrl+Click to add vertex in edit mode
        if ctrl_pressed and self.edit_mode_element and n_press == 1:
            element = self.edit_mode_element
            if element.type == ElementType.CUSTOM_PANEL:
                # Find closest edge and insert vertex
                vertices = element.properties.get("vertices", [])
                if len(vertices) >= 3:
                    # Convert click to element-relative coordinates
                    rel_x = page_x - element.x
                    rel_y = page_y - element.y
                    
                    # Find closest edge
                    closest_edge = None
                    min_distance = float('inf')
                    
                    for i in range(len(vertices)):
                        v1 = vertices[i]
                        v2 = vertices[(i + 1) % len(vertices)]
                        
                        # Extract coordinates
                        v1x, v1y = v1 if isinstance(v1, (list, tuple)) else (v1.get("x", 0), v1.get("y", 0))
                        v2x, v2y = v2 if isinstance(v2, (list, tuple)) else (v2.get("x", 0), v2.get("y", 0))
                        
                        # Calculate distance from point to line segment
                        distance = self._point_to_segment_distance(rel_x, rel_y, v1x, v1y, v2x, v2y)
                        
                        if distance < min_distance:
                            min_distance = distance
                            closest_edge = i
                    
                    # If close enough to an edge (within 10 pixels), insert vertex
                    if closest_edge is not None and min_distance < 10 / scale:
                        # Insert new vertex after closest_edge
                        new_vertices = vertices[:closest_edge + 1] + [(rel_x, rel_y)] + vertices[closest_edge + 1:]
                        element.properties["vertices"] = new_vertices
                        self._update_custom_panel_bounds(element)
                        self.canvas.queue_draw()
                        return
        
        # Find clicked element (top to bottom)
        clicked_element = None
        handle_margin = 8 / scale  # Add margin for resize handles
        
        for element in reversed(self.current_page.elements):
            # Check panel bounds
            in_panel = (element.x <= page_x <= element.x + element.width and
                       element.y <= page_y <= element.y + element.height)
            
            # If element is selected in image mode, also check image bounds (which may extend outside panel)
            # Include margin for resize handles
            in_image = False
            if (element in self.selected_elements and 
                self.selection_mode == 'image' and
                (element.type == ElementType.PANEL or element.type == ElementType.CUSTOM_PANEL) and
                element.properties.get("image")):
                
                image_width = element.properties.get("image_width", element.width)
                image_height = element.properties.get("image_height", element.height)
                offset_x = element.properties.get("image_offset_x", (element.width - image_width) / 2)
                offset_y = element.properties.get("image_offset_y", (element.height - image_height) / 2)
                
                img_x = element.x + offset_x
                img_y = element.y + offset_y
                
                # Expand bounds to include handle margin
                in_image = (img_x - handle_margin <= page_x <= img_x + image_width + handle_margin and
                           img_y - handle_margin <= page_y <= img_y + image_height + handle_margin)
            
            if in_panel or in_image:
                clicked_element = element
                break
        
        # Update selection based on single or double click
        if clicked_element:
            if n_press == 1:
                # Single click
                if clicked_element in self.selected_elements:
                    # Clicking on already selected element - keep current mode (sticky image selection)
                    pass
                else:
                    # Clicking on different element - select it in panel mode
                    self.selected_elements = [clicked_element]
                    self.selection_mode = 'panel'
            elif n_press == 2:
                # Double click - toggle between panel and image mode
                if clicked_element in self.selected_elements:
                    if self.selection_mode == 'panel':
                        # Panel mode -> Image mode (if panel has image)
                        if ((clicked_element.type == ElementType.PANEL or 
                             clicked_element.type == ElementType.CUSTOM_PANEL) and
                            clicked_element.properties.get("image")):
                            self.selection_mode = 'image'
                    else:
                        # Image mode -> Panel mode
                        self.selection_mode = 'panel'
                else:
                    # Double clicking on new element - select and go to image mode if available
                    self.selected_elements = [clicked_element]
                    if ((clicked_element.type == ElementType.PANEL or
                         clicked_element.type == ElementType.CUSTOM_PANEL) and
                        clicked_element.properties.get("image")):
                        self.selection_mode = 'image'
                    else:
                        self.selection_mode = 'panel'
        else:
            # Clicked on empty space
            self.selected_elements = []
            self.selection_mode = 'panel'
        
        self._update_layer_buttons()
        self.canvas.queue_draw()
    
    def _on_canvas_right_click(self, gesture, n_press, x, y):
        """Handle right-click on canvas for context menu."""
        if not self.current_page or not self.selected_elements:
            return
        
        element = self.selected_elements[0]
        
        # Only show context menu for custom panels and spline-based speech bubbles
        is_custom_panel = element.type == ElementType.CUSTOM_PANEL
        is_spline_bubble = (element.type == ElementType.SPEECH_BUBBLE and 
                           element.properties.get("bubble_type") == "round" and
                           element.properties.get("control_points") is not None)
        
        if not (is_custom_panel or is_spline_bubble):
            return
        
        # Create context menu
        menu = Gio.Menu()
        
        if element == self.edit_mode_element:
            # Currently in edit mode - offer to exit
            menu.append("Exit Edit Mode", "win.exit_edit_mode")
        else:
            # Not in edit mode - offer to enter
            menu.append("Edit Shape", "win.enter_edit_mode")
        
        # Create and show popover menu
        popover = Gtk.PopoverMenu()
        popover.set_menu_model(menu)
        popover.set_parent(self.canvas)
        
        # Position popover at click location
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        
        popover.popup()
    
    def _on_drag_begin(self, gesture, start_x, start_y):
        """Handle drag begin for moving/resizing elements or panning (Shift+drag)."""
        if not self.current_page:
            return
        
        # Check if Shift key is pressed for panning
        event = gesture.get_current_event()
        modifiers = event.get_modifier_state()
        if modifiers & Gdk.ModifierType.SHIFT_MASK:
            # Start panning mode
            self.panning = True
            
            # Store the current accumulated pan offset as the baseline for this drag
            self.pan_start_offset_x = self.pan_offset_x
            self.pan_start_offset_y = self.pan_offset_y
            
            self.canvas.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))
            return
        
        # Normal element dragging - require a selected element
        if not self.selected_elements:
            return
        
        element = self.selected_elements[0]
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        
        # Use padding + pan_offset for coordinate transformation (same as draw function)
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        
        # Convert canvas coordinates to page coordinates
        page_x = (start_x - x_offset) / scale
        page_y = (start_y - y_offset) / scale
        
        # Check if clicking on custom panel vertex handle in edit mode (not in image mode)
        if (element.type == ElementType.CUSTOM_PANEL and 
            element == self.edit_mode_element and 
            self.selection_mode != 'image'):
            vertices = element.properties.get("vertices", [])
            handle_size = 8 / scale
            
            for i, vertex in enumerate(vertices):
                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                vertex_x = element.x + vx
                vertex_y = element.y + vy
                
                # Check if click is on this vertex handle
                if (abs(page_x - vertex_x) < handle_size and
                    abs(page_y - vertex_y) < handle_size):
                    # Select this vertex and start dragging
                    self.selected_vertex = i
                    self.dragging_vertex = i
                    self.drag_start_x = page_x
                    self.drag_start_y = page_y
                    # Store initial vertex position
                    self.vertex_start_x = vx
                    self.vertex_start_y = vy
                    return
        
        # Check if clicking on speech bubble handles
        if element.type == ElementType.SPEECH_BUBBLE:
            control_points = element.properties.get("control_points")
            
            if control_points:  # Spline-based bubble
                handle_size = 8 / scale
                
                # Scale control points to page coordinates
                scaled_points = [(element.x + px, element.y + py) for px, py in control_points]
                
                # Get tail properties
                tail_base_t = element.properties.get("tail_base_t", 0.75)
                tail_tip_x = element.properties.get("tail_tip_x", element.width / 2)
                tail_tip_y = element.properties.get("tail_tip_y", element.height + 50)
                tail_tip_px = element.x + tail_tip_x
                tail_tip_py = element.y + tail_tip_y
                
                # Calculate tail base position
                tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)
                
                # Check if clicking on tail tip handle (bright pink)
                if (abs(page_x - tail_tip_px) < handle_size and
                    abs(page_y - tail_tip_py) < handle_size):
                    self.dragging_tail_tip = True
                    self.drag_start_x = page_x
                    self.drag_start_y = page_y
                    self.tail_start_x = tail_tip_x
                    self.tail_start_y = tail_tip_y
                    return
                
                # Check if clicking on tail base handle (bright pink - constrained to curve)
                if (abs(page_x - tail_base_pos[0]) < handle_size and
                    abs(page_y - tail_base_pos[1]) < handle_size):
                    self.dragging_tail_base = True
                    self.drag_start_x = page_x
                    self.drag_start_y = page_y
                    self.tail_base_t_start = tail_base_t
                    return
                
                # Check if clicking on control point handles (green - only in edit mode)
                if element == self.edit_mode_element:
                    for i, (px, py) in enumerate(scaled_points):
                        if (abs(page_x - px) < handle_size and
                            abs(page_y - py) < handle_size):
                            self.dragging_bubble_control = i
                            self.drag_start_x = page_x
                            self.drag_start_y = page_y
                            # Store start position relative to element origin
                            self.vertex_start_x = control_points[i][0]
                            self.vertex_start_y = control_points[i][1]
                            return
            else:
                # Old-style bubble (fallback)
                tail_tip_x = element.properties.get("tail_tip_x", element.width / 2)
                tail_tip_y = element.properties.get("tail_tip_y", element.height + 50)
                
                handle_size = 8 / scale
                if (abs(page_x - (element.x + tail_tip_x)) < handle_size and
                    abs(page_y - (element.y + tail_tip_y)) < handle_size):
                    self.dragging_element = element
                    self.dragging_tail = True
                    self.drag_start_x = page_x
                    self.drag_start_y = page_y
                    self.tail_start_x = tail_tip_x
                    self.tail_start_y = tail_tip_y
                    return
        
        # Handle based on selection mode
        if self.selection_mode == 'image' and (element.type == ElementType.PANEL or element.type == ElementType.CUSTOM_PANEL) and element.properties.get("image"):
            # Image selection mode - work with image bounds
            w = element.width
            h = element.height
            image_filename = element.properties.get("image")
            image_width = element.properties.get("image_width", int(w))
            image_height = element.properties.get("image_height", int(h))
            
            # Get stored offset
            offset_x = element.properties.get("image_offset_x", (w - image_width) / 2)
            offset_y = element.properties.get("image_offset_y", (h - image_height) / 2)
            
            surface = self._get_cached_image_surface(image_filename, int(image_width), int(image_height))
            
            if surface:
                surface_width = surface.get_width()
                surface_height = surface.get_height()
                img_x = element.x + offset_x
                img_y = element.y + offset_y
                
                # Check if clicking on image resize handles
                handle_size = 8 / scale
                handles = {
                    'top-left': (img_x, img_y),
                    'top-right': (img_x + surface_width, img_y),
                    'bottom-left': (img_x, img_y + surface_height),
                    'bottom-right': (img_x + surface_width, img_y + surface_height),
                }
                
                for handle_name, (hx, hy) in handles.items():
                    if (hx - handle_size <= page_x <= hx + handle_size and
                        hy - handle_size <= page_y <= hy + handle_size):
                        # Store image properties for resizing
                        if "image_width" not in element.properties:
                            element.properties["image_width"] = surface_width
                        if "image_height" not in element.properties:
                            element.properties["image_height"] = surface_height
                        
                        self.resizing_element = element
                        self.resizing_image = True
                        self.resize_handle = handle_name
                        self.drag_start_x = page_x
                        self.drag_start_y = page_y
                        self.element_start_width = element.properties.get("image_width", surface_width)
                        self.element_start_height = element.properties.get("image_height", surface_height)
                        # Initialize temp dimensions
                        self.temp_image_width = self.element_start_width
                        self.temp_image_height = self.element_start_height
                        return
                
                # Not on a handle, check if clicking on image body to drag it
                if (img_x <= page_x <= img_x + surface_width and
                    img_y <= page_y <= img_y + surface_height):
                    self.dragging_element = element
                    self.dragging_image = True
                    self.drag_start_x = page_x
                    self.drag_start_y = page_y
                    # Store current offsets
                    self.image_start_offset_x = element.properties.get("image_offset_x", (element.width - surface_width) / 2)
                    self.image_start_offset_y = element.properties.get("image_offset_y", (element.height - surface_height) / 2)
                    return
        else:
            # Panel selection mode - work with panel bounds
            # Skip resize handles if in edit mode for custom panels
            in_edit_mode = (element.type == ElementType.CUSTOM_PANEL and element == self.edit_mode_element)
            
            if not in_edit_mode:
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
                        self.resizing_image = False
                        self.resize_handle = handle_name
                        self.drag_start_x = page_x
                        self.drag_start_y = page_y
                        self.element_start_x = element.x
                        self.element_start_y = element.y
                        self.element_start_width = element.width
                        self.element_start_height = element.height
                        return
            
            # If not on a handle and not in edit mode, start dragging the element
            if (not in_edit_mode and
                element.x <= page_x <= element.x + element.width and
                element.y <= page_y <= element.y + element.height):
                self.dragging_element = element
                self.dragging_image = False
                self.drag_start_x = page_x
                self.drag_start_y = page_y
                self.element_start_x = element.x
                self.element_start_y = element.y
    
    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Handle drag update for moving/resizing elements or panning."""
        # Handle panning (Shift+drag)
        if self.panning:
            # Update pan offsets - add current drag to accumulated offset
            self.pan_offset_x = self.pan_start_offset_x + offset_x
            self.pan_offset_y = self.pan_start_offset_y + offset_y
            # Trigger redraw
            self.canvas.queue_draw()
            return
        
        scale = self.zoom_level / 100.0
        
        # Convert offset from canvas to page coordinates
        dx = offset_x / scale
        dy = offset_y / scale
        
        # Handle vertex dragging for custom panels
        if self.dragging_vertex is not None:
            element = self.selected_elements[0] if self.selected_elements else None
            if element and element.type == ElementType.CUSTOM_PANEL:
                vertices = element.properties.get("vertices", [])
                if 0 <= self.dragging_vertex < len(vertices):
                    # Update vertex position based on drag from start position
                    new_x = self.vertex_start_x + dx
                    new_y = self.vertex_start_y + dy
                    
                    # Update vertex (handle both list and tuple formats)
                    if isinstance(vertices[self.dragging_vertex], (list, tuple)):
                        vertices[self.dragging_vertex] = [new_x, new_y]
                    else:
                        vertices[self.dragging_vertex] = {"x": new_x, "y": new_y}
                    
                    element.properties["vertices"] = vertices
                    self.canvas.queue_draw()
            return
        
        # Handle speech bubble control point dragging
        if self.dragging_bubble_control is not None:
            element = self.selected_elements[0] if self.selected_elements else None
            if element and element.type == ElementType.SPEECH_BUBBLE:
                control_points = element.properties.get("control_points", [])
                if 0 <= self.dragging_bubble_control < len(control_points):
                    # Update control point position
                    new_x = self.vertex_start_x + dx
                    new_y = self.vertex_start_y + dy
                    control_points[self.dragging_bubble_control] = (new_x, new_y)
                    element.properties["control_points"] = control_points
                    self.canvas.queue_draw()
            return
        
        # Handle speech bubble tail tip dragging (free movement)
        if self.dragging_tail_tip:
            element = self.selected_elements[0] if self.selected_elements else None
            if element and element.type == ElementType.SPEECH_BUBBLE:
                # Update tail tip position
                element.properties["tail_tip_x"] = self.tail_start_x + dx
                element.properties["tail_tip_y"] = self.tail_start_y + dy
                self.canvas.queue_draw()
            return
        
        # Handle speech bubble tail base dragging (constrained to curve)
        if self.dragging_tail_base:
            element = self.selected_elements[0] if self.selected_elements else None
            if element and element.type == ElementType.SPEECH_BUBBLE:
                control_points = element.properties.get("control_points", [])
                if control_points:
                    # Current mouse position in page coordinates
                    mouse_x = self.drag_start_x + dx
                    mouse_y = self.drag_start_y + dy
                    
                    # Scale control points to page coordinates
                    scaled_points = [(element.x + px, element.y + py) for px, py in control_points]
                    
                    # Find closest point on curve to mouse position
                    closest_t = self._find_closest_point_on_curve(scaled_points, mouse_x, mouse_y)
                    
                    # Update tail_base_t
                    element.properties["tail_base_t"] = closest_t
                    self.canvas.queue_draw()
            return
        
        if self.dragging_element:
            if self.dragging_tail:
                # Moving the speech bubble tail tip
                element = self.dragging_element
                # Update tail tip position based on drag from start position
                element.properties["tail_tip_x"] = self.tail_start_x + dx
                element.properties["tail_tip_y"] = self.tail_start_y + dy
                
                self.canvas.queue_draw()
                return
                
            elif self.dragging_image:
                # Moving the image inside the panel
                element = self.dragging_element
                new_offset_x = self.image_start_offset_x + dx
                new_offset_y = self.image_start_offset_y + dy
                
                # Update image offset (no constraints, allow image to move freely)
                element.properties["image_offset_x"] = new_offset_x
                element.properties["image_offset_y"] = new_offset_y
            else:
                # Move the element/panel
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
            element = self.resizing_element
            
            if self.resizing_image:
                # Resizing the image inside a panel - maintain aspect ratio
                # Calculate the aspect ratio from the original image size
                aspect_ratio = self.element_start_width / self.element_start_height
                
                # Determine new size based on the handle being dragged
                if self.resize_handle in ['top-right', 'bottom-right']:
                    # Right side handles - use width change
                    new_width = self.element_start_width + dx
                    new_height = new_width / aspect_ratio
                elif self.resize_handle in ['top-left', 'bottom-left']:
                    # Left side handles - use width change (inverted)
                    new_width = self.element_start_width - dx
                    new_height = new_width / aspect_ratio
                else:
                    new_width = self.element_start_width
                    new_height = self.element_start_height
                
                # Enforce minimum size and update temp dimensions only
                if new_width > 20 and new_height > 20:
                    self.temp_image_width = new_width
                    self.temp_image_height = new_height
                
                self.canvas.queue_draw()
            else:
                # Resizing the panel itself
                # For custom panels, we need to scale vertices
                is_custom_panel = element.type == ElementType.CUSTOM_PANEL
                
                if self.resize_handle == 'top-left':
                    new_x = self.element_start_x + dx
                    new_y = self.element_start_y + dy
                    new_width = self.element_start_width - dx
                    new_height = self.element_start_height - dy
                    
                    if new_width > 20 and new_height > 20:
                        if is_custom_panel:
                            # Scale vertices proportionally
                            scale_x = new_width / element.width
                            scale_y = new_height / element.height
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        
                        element.x = new_x
                        element.y = new_y
                        element.width = new_width
                        element.height = new_height
                
                elif self.resize_handle == 'top-right':
                    new_y = self.element_start_y + dy
                    new_width = self.element_start_width + dx
                    new_height = self.element_start_height - dy
                    
                    if new_width > 20 and new_height > 20:
                        if is_custom_panel:
                            # Scale vertices proportionally
                            scale_x = new_width / element.width
                            scale_y = new_height / element.height
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        
                        element.y = new_y
                        element.width = new_width
                        element.height = new_height
                
                elif self.resize_handle == 'bottom-left':
                    new_x = self.element_start_x + dx
                    new_width = self.element_start_width - dx
                    new_height = self.element_start_height + dy
                    
                    if new_width > 20 and new_height > 20:
                        if is_custom_panel:
                            # Scale vertices proportionally
                            scale_x = new_width / element.width
                            scale_y = new_height / element.height
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        
                        element.x = new_x
                        element.width = new_width
                        element.height = new_height
                
                elif self.resize_handle == 'bottom-right':
                    new_width = self.element_start_width + dx
                    new_height = self.element_start_height + dy
                    
                    if new_width > 20 and new_height > 20:
                        if is_custom_panel:
                            # Scale vertices proportionally
                            scale_x = new_width / element.width
                            scale_y = new_height / element.height
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        
                        element.width = new_width
                        element.height = new_height
                
                self.canvas.queue_draw()
    
    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle drag end."""
        # If we were panning, just stop - keep the accumulated offset
        if self.panning:
            self.panning = False
            self.canvas.set_cursor(None)
            # Don't reset pan_offset - keep it accumulated for future draws
            return
        
        # If we were resizing an image, apply the final dimensions and clear cache
        if self.resizing_image and self.resizing_element:
            element = self.resizing_element
            image_filename = element.properties.get("image")
            
            # Clear old cache entries for this image
            keys_to_remove = [k for k in self.image_cache.keys() if k[0] == image_filename]
            for key in keys_to_remove:
                del self.image_cache[key]
            
            # Apply the final dimensions
            element.properties["image_width"] = self.temp_image_width
            element.properties["image_height"] = self.temp_image_height
            
            # Trigger a redraw to load the image at the new size
            self.canvas.queue_draw()
        
        # If we were dragging a vertex, update panel bounds
        if self.dragging_vertex is not None and self.selected_elements:
            element = self.selected_elements[0]
            if element.type == ElementType.CUSTOM_PANEL:
                self._update_custom_panel_bounds(element)
        
        self.dragging_element = None
        self.dragging_image = False
        self.dragging_tail = False
        self.dragging_vertex = None
        self.tail_start_x = 0
        self.tail_start_y = 0
        self.vertex_start_x = 0
        self.vertex_start_y = 0
        self.resizing_element = None
        self.resizing_image = False
        self.resize_handle = None
        self.temp_image_width = 0
        self.temp_image_height = 0
        self.image_start_offset_x = 0
        self.image_start_offset_y = 0
        
        # Reset speech bubble drag flags
        self.dragging_bubble_control = None
        self.dragging_tail_tip = False
        self.dragging_tail_base = False
        self.tail_base_t_start = 0
    
    def _on_canvas_motion(self, controller, x, y):
        """Handle mouse motion for cursor changes."""
        if not self.current_page:
            self.canvas.set_cursor(None)  # Default cursor
            return
        
        # Check if Shift key is held for panning mode
        event = controller.get_current_event()
        if event:
            modifiers = event.get_modifier_state()
            if modifiers & Gdk.ModifierType.SHIFT_MASK:
                # Shift is held - show grab cursor for panning
                self.canvas.set_cursor(Gdk.Cursor.new_from_name("grab", None))
                return
        
        # Calculate position relative to page
        scale = self.zoom_level / 100.0
        page_width = self.current_page.width * scale
        page_height = self.current_page.height * scale
        # Use padding + pan_offset for coordinate transformation (same as draw function)
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        
        # Convert canvas coordinates to page coordinates
        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale
        
        handle_size = 8 / scale
        
        # Check if hovering over selected element
        if self.selected_elements:
            element = self.selected_elements[0]
            
            if self.selection_mode == 'image' and (element.type == ElementType.PANEL or element.type == ElementType.CUSTOM_PANEL) and element.properties.get("image"):
                # Image mode - check image handles and body
                w = element.width
                h = element.height
                image_width = element.properties.get("image_width", w)
                image_height = element.properties.get("image_height", h)
                offset_x = element.properties.get("image_offset_x", (w - image_width) / 2)
                offset_y = element.properties.get("image_offset_y", (h - image_height) / 2)
                
                img_x = element.x + offset_x
                img_y = element.y + offset_y
                
                # Check if on image resize handles
                handles = {
                    'nw-resize': (img_x, img_y),
                    'ne-resize': (img_x + image_width, img_y),
                    'sw-resize': (img_x, img_y + image_height),
                    'se-resize': (img_x + image_width, img_y + image_height),
                }
                
                for cursor_name, (hx, hy) in handles.items():
                    if (hx - handle_size <= page_x <= hx + handle_size and
                        hy - handle_size <= page_y <= hy + handle_size):
                        # On image resize handle - use resize cursor
                        self.canvas.set_cursor(Gdk.Cursor.new_from_name(cursor_name, None))
                        return
                
                # Check if on image body
                if (img_x <= page_x <= img_x + image_width and
                    img_y <= page_y <= img_y + image_height):
                    # On image body - use move cursor
                    self.canvas.set_cursor(Gdk.Cursor.new_from_name("move", None))
                    return
                    
            elif self.selection_mode == 'panel':
                # Panel mode - check panel handles and body
                # Skip resize cursors if in edit mode for custom panels
                in_edit_mode = (element.type == ElementType.CUSTOM_PANEL and element == self.edit_mode_element)
                
                if not in_edit_mode:
                    # Check if on panel resize handles
                    handles = {
                        'nw-resize': (element.x, element.y),
                        'ne-resize': (element.x + element.width, element.y),
                        'sw-resize': (element.x, element.y + element.height),
                        'se-resize': (element.x + element.width, element.y + element.height),
                    }
                    
                    for cursor_name, (hx, hy) in handles.items():
                        if (hx - handle_size <= page_x <= hx + handle_size and
                            hy - handle_size <= page_y <= hy + handle_size):
                            # On panel resize handle - use resize cursor
                            self.canvas.set_cursor(Gdk.Cursor.new_from_name(cursor_name, None))
                            return
                
                # Check if on panel body (or in edit mode - show default cursor)
                if (element.x <= page_x <= element.x + element.width and
                    element.y <= page_y <= element.y + element.height):
                    # On panel body - use move cursor (unless in edit mode)
                    if not in_edit_mode:
                        self.canvas.set_cursor(Gdk.Cursor.new_from_name("move", None))
                    else:
                        # In edit mode - show default cursor (crosshair could be added later)
                        self.canvas.set_cursor(None)
                    return
        
        # Default cursor
        self.canvas.set_cursor(None)
    
    def _on_bring_to_front(self, button):
        """Bring selected element to front."""
        if self.selected_elements and self.current_page:
            self.current_page.bring_to_front(self.selected_elements[0])
            self._update_layer_buttons()
            self.canvas.queue_draw()
    
    def _on_bring_forward(self, button):
        """Bring selected element forward one layer."""
        if self.selected_elements and self.current_page:
            self.current_page.bring_forward(self.selected_elements[0])
            self._update_layer_buttons()
            self.canvas.queue_draw()
    
    def _on_send_backward(self, button):
        """Send selected element backward one layer."""
        if self.selected_elements and self.current_page:
            self.current_page.send_backward(self.selected_elements[0])
            self._update_layer_buttons()
            self.canvas.queue_draw()
    
    def _on_send_to_back(self, button):
        """Send selected element to back."""
        if self.selected_elements and self.current_page:
            self.current_page.send_to_back(self.selected_elements[0])
            self._update_layer_buttons()
            self.canvas.queue_draw()
    
    def _update_layer_buttons(self):
        """Enable/disable layer buttons based on selection."""
        has_selection = len(self.selected_elements) > 0
        self.bring_front_btn.set_sensitive(has_selection)
        self.bring_forward_btn.set_sensitive(has_selection)
        self.send_backward_btn.set_sensitive(has_selection)
        self.send_back_btn.set_sensitive(has_selection)
    
    def _on_close_request(self, window):
        """Handle window close request."""
        if self.on_close_callback:
            self.on_close_callback(self)
        return False
