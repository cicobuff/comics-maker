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
        
        # Element manipulation state
        self.dragging_element = None
        self.dragging_image = False  # True if dragging the image inside a panel
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
                        
                        # Scale to fit within current panel while maintaining aspect ratio
                        scale_x = w / img_width
                        scale_y = h / img_height
                        scale_factor = min(scale_x, scale_y)
                        
                        element.properties["image_width"] = img_width * scale_factor
                        element.properties["image_height"] = img_height * scale_factor
                        
                        # Store initial centered offset (relative to panel)
                        element.properties["image_offset_x"] = (w - img_width * scale_factor) / 2
                        element.properties["image_offset_y"] = (h - img_height * scale_factor) / 2
                
                # Use stored image dimensions
                image_width = element.properties.get("image_width", int(w))
                image_height = element.properties.get("image_height", int(h))
                
                # Use stored offset, or default to centered
                offset_x = element.properties.get("image_offset_x", (w - image_width) / 2)
                offset_y = element.properties.get("image_offset_y", (h - image_height) / 2)
                
                # Draw the image with caching
                surface = self._get_cached_image_surface(image_filename, int(image_width), int(image_height))
                
                if surface:
                    # The surface is already the correct size
                    surface_width = surface.get_width()
                    surface_height = surface.get_height()
                    
                    # Position image using stored offset (anchored to top-left of panel)
                    img_x = x + offset_x
                    img_y = y + offset_y
                    
                    # Draw the image
                    cr.save()
                    cr.translate(img_x, img_y)
                    cr.set_source_surface(surface, 0, 0)
                    cr.paint()
                    cr.restore()
                    
                    # If currently resizing this image, draw a preview rectangle at the new size
                    if (self.resizing_image and self.resizing_element == element and 
                        element in self.selected_elements and self.selection_mode == 'image'):
                        preview_x = x + offset_x
                        preview_y = y + offset_y
                        
                        # Draw semi-transparent overlay
                        cr.set_source_rgba(1.0, 0.0, 0.0, 0.2)  # Red with transparency
                        cr.rectangle(preview_x, preview_y, self.temp_image_width, self.temp_image_height)
                        cr.fill()
                        
                        # Draw solid outline
                        cr.set_source_rgb(1.0, 0.0, 0.0)  # Red
                        cr.set_line_width(3)
                        cr.rectangle(preview_x, preview_y, self.temp_image_width, self.temp_image_height)
                        cr.stroke()
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
        
        else:
            # Draw other element types (shapes, text, etc.)
            self._draw_other_elements(cr, element, x, y, w, h)
        
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
            
            elif self.selection_mode == 'image' and element.type == ElementType.PANEL and element.properties.get("image"):
                # Image selection - red solid line around the actual image
                image_filename = element.properties.get("image")
                image_width = element.properties.get("image_width", int(w))
                image_height = element.properties.get("image_height", int(h))
                
                # Get stored offset
                offset_x = element.properties.get("image_offset_x", (w - image_width) / 2)
                offset_y = element.properties.get("image_offset_y", (h - image_height) / 2)
                
                # Use temporary dimensions if currently resizing
                if self.resizing_image and self.resizing_element == element:
                    display_width = self.temp_image_width
                    display_height = self.temp_image_height
                else:
                    surface = self._get_cached_image_surface(image_filename, int(image_width), int(image_height))
                    if surface:
                        display_width = surface.get_width()
                        display_height = surface.get_height()
                    else:
                        display_width = image_width
                        display_height = image_height
                
                img_x = x + offset_x
                img_y = y + offset_y
                
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
    
    def _draw_other_elements(self, cr, element, x, y, w, h):
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
        canvas_width = self.canvas.get_width()
        canvas_height = self.canvas.get_height()
        
        x_offset = max((canvas_width - page_width) / 2, 0)
        y_offset = max((canvas_height - page_height) / 2, 0)
        
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
        canvas_width = self.canvas.get_width()
        canvas_height = self.canvas.get_height()
        
        x_offset = max((canvas_width - page_width) / 2, 0)
        y_offset = max((canvas_height - page_height) / 2, 0)
        
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
            if (element.type == ElementType.PANEL and
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
            # Check panel bounds
            in_panel = (element.x <= page_x <= element.x + element.width and
                       element.y <= page_y <= element.y + element.height)
            
            # If element is selected in image mode, also check image bounds (which may extend outside panel)
            in_image = False
            if (element in self.selected_elements and 
                self.selection_mode == 'image' and
                element.type == ElementType.PANEL and
                element.properties.get("image")):
                
                image_width = element.properties.get("image_width", element.width)
                image_height = element.properties.get("image_height", element.height)
                offset_x = element.properties.get("image_offset_x", (element.width - image_width) / 2)
                offset_y = element.properties.get("image_offset_y", (element.height - image_height) / 2)
                
                img_x = element.x + offset_x
                img_y = element.y + offset_y
                
                in_image = (img_x <= page_x <= img_x + image_width and
                           img_y <= page_y <= img_y + image_height)
            
            if in_panel or in_image:
                clicked_element = element
                break
        
        # Update selection
        if clicked_element:
            # Check if clicking on a resize handle - if so, don't toggle selection mode
            if clicked_element in self.selected_elements:
                handle_size = 8 / scale
                
                # Check panel resize handles
                if self.selection_mode == 'panel':
                    handles = [
                        (clicked_element.x, clicked_element.y),
                        (clicked_element.x + clicked_element.width, clicked_element.y),
                        (clicked_element.x, clicked_element.y + clicked_element.height),
                        (clicked_element.x + clicked_element.width, clicked_element.y + clicked_element.height),
                    ]
                    on_handle = any(hx - handle_size <= page_x <= hx + handle_size and
                                   hy - handle_size <= page_y <= hy + handle_size
                                   for hx, hy in handles)
                    
                    if not on_handle:
                        # Not on a handle, check if we should toggle to image mode
                        if (clicked_element.type == ElementType.PANEL and
                            clicked_element.properties.get("image")):
                            self.selection_mode = 'image'
                elif self.selection_mode == 'image':
                    # In image mode - check if clicking on image resize handles first
                    w = clicked_element.width
                    h = clicked_element.height
                    image_width = clicked_element.properties.get("image_width", int(w))
                    image_height = clicked_element.properties.get("image_height", int(h))
                    offset_x = clicked_element.properties.get("image_offset_x", (w - image_width) / 2)
                    offset_y = clicked_element.properties.get("image_offset_y", (h - image_height) / 2)
                    
                    img_x = clicked_element.x + offset_x
                    img_y = clicked_element.y + offset_y
                    
                    # Check if clicking on image resize handles (don't toggle if on handle)
                    handles = [
                        (img_x, img_y),
                        (img_x + image_width, img_y),
                        (img_x, img_y + image_height),
                        (img_x + image_width, img_y + image_height),
                    ]
                    on_handle = any(hx - handle_size <= page_x <= hx + handle_size and
                                   hy - handle_size <= page_y <= hy + handle_size
                                   for hx, hy in handles)
                    
                    if not on_handle:
                        # Not on a handle, check bounds to decide if we should toggle
                        # Check if clicking inside the image bounds
                        in_image_bounds = (img_x <= page_x <= img_x + image_width and
                                          img_y <= page_y <= img_y + image_height)
                        
                        # Check if clicking inside the panel bounds
                        in_panel_bounds = (clicked_element.x <= page_x <= clicked_element.x + clicked_element.width and
                                          clicked_element.y <= page_y <= clicked_element.y + clicked_element.height)
                        
                        # Only toggle back to panel mode if clicking inside panel but outside image
                        if in_panel_bounds and not in_image_bounds:
                            self.selection_mode = 'panel'
                        # Otherwise stay in image mode (clicking on image body, even if outside panel)
            else:
                # New selection - start with panel mode
                self.selected_elements = [clicked_element]
                self.selection_mode = 'panel'
        else:
            self.selected_elements = []
            self.selection_mode = 'panel'
        
        self._update_layer_buttons()
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
        
        # Handle based on selection mode
        if self.selection_mode == 'image' and element.type == ElementType.PANEL and element.properties.get("image"):
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
            
            # If not on a handle, start dragging the element
            if (element.x <= page_x <= element.x + element.width and
                element.y <= page_y <= element.y + element.height):
                self.dragging_element = element
                self.dragging_image = False
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
            if self.dragging_image:
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
        
        self.dragging_element = None
        self.dragging_image = False
        self.resizing_element = None
        self.resizing_image = False
        self.resize_handle = None
        self.temp_image_width = 0
        self.temp_image_height = 0
        self.image_start_offset_x = 0
        self.image_start_offset_y = 0
    
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
