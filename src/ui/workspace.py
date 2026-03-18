import gi
gi.require_version('Gtk', '4.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gio, Gdk, GLib, Pango, PangoCairo
from ..models.project import Project
from ..models.element import Element, ElementType
from ..core.undo_manager import UndoManager, MoveResizeCommand, AddElementCommand, RemoveElementCommand
import copy


def _get_available_fonts():
    """Get sorted list of all available font families from PangoCairo."""
    font_map = PangoCairo.FontMap.get_default()
    families = font_map.list_families()
    names = sorted({f.get_name() for f in families}, key=str.casefold)
    return names


_AVAILABLE_FONTS = _get_available_fonts()


_font_attr_cache = {}


def _get_font_attrs(name):
    """Get cached Pango AttrList for a font name."""
    if name not in _font_attr_cache:
        desc = Pango.FontDescription.from_string(name)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_font_desc_new(desc))
        _font_attr_cache[name] = attrs
    return _font_attr_cache[name]


def _on_font_item_setup(factory, list_item):
    label = Gtk.Label(xalign=0)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    list_item.set_child(label)


def _on_font_item_bind(factory, list_item):
    label = list_item.get_child()
    name = list_item.get_item().get_string()
    label.set_text(name)
    label.set_attributes(_get_font_attrs(name))


def _create_font_combo():
    """Create a DropDown with virtualized, lazily rendered font previews."""
    string_list = Gtk.StringList()
    for name in _AVAILABLE_FONTS:
        string_list.append(name)

    factory = Gtk.SignalListItemFactory()
    factory.connect("setup", _on_font_item_setup)
    factory.connect("bind", _on_font_item_bind)

    dropdown = Gtk.DropDown(model=string_list)
    dropdown.set_factory(factory)
    dropdown.set_enable_search(True)
    dropdown.set_selected(0)
    return dropdown


def _get_combo_font(combo):
    """Get the active font name from a font DropDown."""
    item = combo.get_selected_item()
    if item:
        return item.get_string()
    return None


def _set_combo_font(combo, font_name):
    """Set the active font by name, appending if not found."""
    model = combo.get_model()
    for i in range(model.get_n_items()):
        if model.get_string(i) == font_name:
            combo.set_selected(i)
            return
    model.append(font_name)
    combo.set_selected(model.get_n_items() - 1)


def _start_font_cache_warmup():
    """Pre-warm font loading in background idle callbacks."""
    font_iter = iter(_AVAILABLE_FONTS)
    font_map = PangoCairo.FontMap.get_default()
    context = font_map.create_context()

    def _warmup_batch():
        for _ in range(5):
            try:
                name = next(font_iter)
                desc = Pango.FontDescription.from_string(name)
                font_map.load_font(context, desc)
                _get_font_attrs(name)
            except StopIteration:
                return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.idle_add(_warmup_batch)


_start_font_cache_warmup()


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

        # Rotation state for TEXT / TEXTAREA
        self.rotation_mode = False  # True when rotation handle is active
        self.rotating_element = None  # Element being rotated during drag
        self.rotation_start_angle = 0  # Element angle at drag start
        self.rotation_drag_start_angle = 0  # Mouse angle at drag start

        # Speech bubble properties panel state
        self._updating_properties = False

        # Image library lazy-load queue
        self._image_lib_load_queue = []

        # Gridline state
        self.gridlines_visible = True
        self.dragging_gridline = None  # ("h", index) or ("v", index)
        self.gridline_snap_threshold = 10  # pixels in page coordinates
        
        # Internal clipboard for copy/paste (list of element dicts)
        self._clipboard_elements = []

        # Undo pre-state captured at drag start
        self._undo_pre_state = None

        # Image cache to avoid reloading images on every frame
        self.image_cache = {}  # key: (filename, width, height), value: cairo surface
        
        self.set_title(f"Comics Maker - {project.name}")
        # Size window to 90% of desktop height, maintain 16:10 aspect
        display = Gdk.Display.get_default()
        if display:
            monitors = display.get_monitors()
            if monitors.get_n_items() > 0:
                monitor = monitors.get_item(0)
                geom = monitor.get_geometry()
                win_height = int(geom.height * 0.9)
                win_width = int(win_height * 16 / 10)
                self.set_default_size(win_width, win_height)
            else:
                self.set_default_size(1400, 900)
        else:
            self.set_default_size(1400, 900)

        # Connect to close request signal
        self.connect("close-request", self._on_close_request)

        # Add key controller at window level for Ctrl+ and Ctrl- shortcuts
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # Show a loading indicator first, defer heavy UI building
        self._loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._loading_box.set_valign(Gtk.Align.CENTER)
        self._loading_box.set_halign(Gtk.Align.CENTER)
        self._loading_spinner = Gtk.Spinner()
        self._loading_spinner.set_size_request(48, 48)
        self._loading_spinner.start()
        self._loading_box.append(self._loading_spinner)
        self._loading_box.append(Gtk.Label(label="Loading workspace…"))
        self.set_child(self._loading_box)

        # Build the real UI after the window has been presented and rendered
        from gi.repository import GLib
        GLib.timeout_add(100, self._deferred_build_ui)

    def _deferred_build_ui(self):
        """Build the full workspace UI after the window is visible."""
        self._build_ui()

        if self.project.pages:
            self.current_page = self.project.pages[0]
            self._refresh_pages_list()
            self._update_canvas_size()

        self._loading_spinner.stop()
        # Fit page to canvas height once layout is realized
        self._initial_zoom_pending = True
        self._initial_zoom_handler = self.canvas.connect("notify::height", self._on_canvas_height_allocated)
        return False

    def _on_canvas_height_allocated(self, widget, pspec):
        """Triggered when canvas height changes; used for initial zoom fit."""
        if not self._initial_zoom_pending:
            return
        viewport_height = self.scrolled.get_height()
        if viewport_height > 1 and self.current_page:
            self._initial_zoom_pending = False
            self.canvas.disconnect(self._initial_zoom_handler)
            self._on_full_page(None, None)
    
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

        # Wrap center_and_right + image library in another paned
        self.outer_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.outer_paned.set_start_child(center_and_right)
        self.outer_paned.set_resize_start_child(True)

        self.image_library_panel = self._create_image_library_panel()
        self.image_library_panel.set_visible(False)
        self.outer_paned.set_end_child(self.image_library_panel)
        self.outer_paned.set_resize_end_child(False)
        self.outer_paned.set_shrink_end_child(False)

        paned_h.set_end_child(self.outer_paned)
        
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
        
        fit_page_btn = Gtk.Button(label="Fit Page")
        fit_page_btn.connect("clicked", lambda b: self._on_full_page(None, None))
        toolbar.append(fit_page_btn)

        fit_width_btn = Gtk.Button(label="Fit Width")
        fit_width_btn.connect("clicked", lambda b: self._on_page_width(None, None))
        toolbar.append(fit_width_btn)

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

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Gridline buttons
        grid_label = Gtk.Label(label="Guides:")
        toolbar.append(grid_label)

        add_hguide_btn = Gtk.Button(label="— H")
        add_hguide_btn.set_tooltip_text("Add Horizontal Guideline")
        add_hguide_btn.connect("clicked", self._on_add_h_gridline)
        toolbar.append(add_hguide_btn)

        add_vguide_btn = Gtk.Button(label="| V")
        add_vguide_btn.set_tooltip_text("Add Vertical Guideline")
        add_vguide_btn.connect("clicked", self._on_add_v_gridline)
        toolbar.append(add_vguide_btn)

        self.toggle_guides_btn = Gtk.ToggleButton(label="Show")
        self.toggle_guides_btn.set_tooltip_text("Toggle Guideline Visibility")
        self.toggle_guides_btn.set_active(True)
        self.toggle_guides_btn.connect("toggled", self._on_toggle_gridlines)
        toolbar.append(self.toggle_guides_btn)

        clear_guides_btn = Gtk.Button(label="Clear")
        clear_guides_btn.set_tooltip_text("Remove All Guidelines")
        clear_guides_btn.connect("clicked", self._on_clear_gridlines)
        toolbar.append(clear_guides_btn)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.image_lib_btn = Gtk.ToggleButton(label="Image Library")
        self.image_lib_btn.set_tooltip_text("Toggle Image Library Panel")
        self.image_lib_btn.connect("toggled", self._on_toggle_image_library)
        toolbar.append(self.image_lib_btn)

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
        """Create the right elements panel with properties section."""
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

        # Rect Panel button
        rect_panel_btn = self._create_draggable_button("Rect Panel", "custom_panel")
        elements_box.append(rect_panel_btn)

        # Circle Panel button
        circle_panel_btn = self._create_draggable_button("Circle Panel", "circle_panel")
        elements_box.append(circle_panel_btn)

        text_label = Gtk.Label(label="Text", xalign=0)
        text_label.add_css_class("heading")
        elements_box.append(text_label)

        # Text Area button
        textarea_btn = self._create_draggable_button("Text Area", "textarea")
        elements_box.append(textarea_btn)

        # Title Text button
        title_text_btn = self._create_draggable_button("Title Text", "text")
        elements_box.append(title_text_btn)

        bubble_label = Gtk.Label(label="Speech Bubbles", xalign=0)
        bubble_label.add_css_class("heading")
        elements_box.append(bubble_label)

        # Single unified speech bubble button
        bubble_btn = self._create_draggable_button("Speech Bubble", "speech_bubble")
        elements_box.append(bubble_btn)

        scrolled.set_child(elements_box)
        box.append(scrolled)

        # Properties panel (hidden by default, shown when speech bubble selected)
        self.properties_panel = self._create_bubble_properties_panel()
        self.properties_panel.set_visible(False)
        box.append(self.properties_panel)

        # Text properties panel (hidden by default, shown when text element selected)
        self.text_properties_panel = self._create_text_properties_panel()
        self.text_properties_panel.set_visible(False)
        box.append(self.text_properties_panel)

        # Textarea properties panel (hidden by default, shown when textarea selected)
        self.textarea_properties_panel = self._create_textarea_properties_panel()
        self.textarea_properties_panel.set_visible(False)
        box.append(self.textarea_properties_panel)

        # Panel properties panel (hidden by default, shown when panel/custom panel/circle panel selected)
        self.panel_properties_panel = self._create_panel_properties_panel()
        self.panel_properties_panel.set_visible(False)
        box.append(self.panel_properties_panel)

        return box

    def _create_bubble_properties_panel(self):
        """Create the speech bubble properties panel."""
        frame = Gtk.Frame(label="Bubble Properties")
        frame.set_margin_start(5)
        frame.set_margin_end(5)
        frame.set_margin_bottom(5)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(300)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.set_margin_start(8)
        panel.set_margin_end(8)
        panel.set_margin_top(8)
        panel.set_margin_bottom(8)

        # --- Style Section ---
        style_label = Gtk.Label(label="Style", xalign=0)
        style_label.add_css_class("heading")
        panel.append(style_label)

        # Body style dropdown
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Body:", xalign=0))
        self.prop_body_style = Gtk.ComboBoxText()
        self._body_styles = ["smooth", "jagged", "dotted", "cloud"]
        for s in self._body_styles:
            self.prop_body_style.append_text(s.capitalize())
        self.prop_body_style.set_active(0)
        self.prop_body_style.set_hexpand(True)
        self.prop_body_style.connect("changed", self._on_prop_body_style_changed)
        row.append(self.prop_body_style)
        panel.append(row)

        # Tail style dropdown
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Tail:", xalign=0))
        self.prop_tail_style = Gtk.ComboBoxText()
        self._tail_styles = ["straight", "circles", "jagged"]
        for s in self._tail_styles:
            self.prop_tail_style.append_text(s.capitalize())
        self.prop_tail_style.set_active(0)
        self.prop_tail_style.set_hexpand(True)
        self.prop_tail_style.connect("changed", self._on_prop_tail_style_changed)
        row.append(self.prop_tail_style)
        panel.append(row)

        panel.append(Gtk.Separator())

        # --- Outline Section ---
        outline_label = Gtk.Label(label="Outline", xalign=0)
        outline_label.add_css_class("heading")
        panel.append(outline_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Width:", xalign=0))
        adj = Gtk.Adjustment(value=1.0, lower=1, upper=20, step_increment=0.5)
        self.prop_outline_width = Gtk.SpinButton(adjustment=adj, digits=1)
        self.prop_outline_width.set_hexpand(True)
        self.prop_outline_width.connect("value-changed", self._on_prop_outline_width_changed)
        row.append(self.prop_outline_width)
        panel.append(row)

        # Tail circles (thought bubble only — hidden for round)
        self.prop_tail_circles_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prop_tail_circles_row.append(Gtk.Label(label="Tail circles:", xalign=0))
        adj = Gtk.Adjustment(value=3, lower=1, upper=10, step_increment=1)
        self.prop_tail_circles = Gtk.SpinButton(adjustment=adj, digits=0)
        self.prop_tail_circles.set_hexpand(True)
        self.prop_tail_circles.connect("value-changed", self._on_prop_tail_circles_changed)
        self.prop_tail_circles_row.append(self.prop_tail_circles)
        panel.append(self.prop_tail_circles_row)

        panel.append(Gtk.Separator())

        # --- Text Section ---
        text_heading = Gtk.Label(label="Text", xalign=0)
        text_heading.add_css_class("heading")
        panel.append(text_heading)

        # Text content (multi-line)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_min_content_height(60)
        text_scroll.set_max_content_height(100)
        self.prop_text_view = Gtk.TextView()
        self.prop_text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prop_text_view.get_buffer().connect("changed", self._on_prop_text_changed)
        text_scroll.set_child(self.prop_text_view)
        panel.append(text_scroll)

        # Font family
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Font:", xalign=0))
        self.prop_font_family = _create_font_combo()
        self.prop_font_family.set_hexpand(True)
        self.prop_font_family.connect("notify::selected", self._on_prop_font_family_changed)
        row.append(self.prop_font_family)
        panel.append(row)

        # Font size
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Size:", xalign=0))
        adj = Gtk.Adjustment(value=14, lower=4, upper=200, step_increment=1)
        self.prop_font_size = Gtk.SpinButton(adjustment=adj, digits=0)
        self.prop_font_size.set_hexpand(True)
        self.prop_font_size.connect("value-changed", self._on_prop_font_size_changed)
        row.append(self.prop_font_size)
        panel.append(row)

        # Text color
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Color:", xalign=0))
        self.prop_text_color = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse("#000000")
        self.prop_text_color.set_rgba(rgba)
        self.prop_text_color.set_hexpand(True)
        self.prop_text_color.connect("color-set", self._on_prop_text_color_changed)
        row.append(self.prop_text_color)
        panel.append(row)

        # Bold / Italic toggles
        style_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prop_bold = Gtk.ToggleButton(label="B")
        self.prop_bold.connect("toggled", self._on_prop_bold_changed)
        style_row.append(self.prop_bold)
        self.prop_italic = Gtk.ToggleButton(label="I")
        self.prop_italic.connect("toggled", self._on_prop_italic_changed)
        style_row.append(self.prop_italic)

        # Text alignment
        self.prop_align_left = Gtk.ToggleButton(label="L")
        self.prop_align_left.set_tooltip_text("Align Left")
        self.prop_align_center = Gtk.ToggleButton(label="C")
        self.prop_align_center.set_tooltip_text("Align Center")
        self.prop_align_center.set_active(True)
        self.prop_align_right = Gtk.ToggleButton(label="R")
        self.prop_align_right.set_tooltip_text("Align Right")
        # Group alignment buttons
        self.prop_align_center.set_group(self.prop_align_left)
        self.prop_align_right.set_group(self.prop_align_left)
        self.prop_align_left.connect("toggled", self._on_prop_text_align_changed)
        self.prop_align_center.connect("toggled", self._on_prop_text_align_changed)
        self.prop_align_right.connect("toggled", self._on_prop_text_align_changed)
        style_row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        style_row.append(self.prop_align_left)
        style_row.append(self.prop_align_center)
        style_row.append(self.prop_align_right)
        panel.append(style_row)

        panel.append(Gtk.Separator())

        # --- Text Area Section ---
        ta_heading = Gtk.Label(label="Text Area", xalign=0)
        ta_heading.add_css_class("heading")
        panel.append(ta_heading)

        for prop_name, prop_label, default_val, attr_name in [
            ("text_area_x", "Left:", 30, "prop_ta_x"),
            ("text_area_y", "Top:", 30, "prop_ta_y"),
            ("text_area_width", "Width:", 140, "prop_ta_w"),
            ("text_area_height", "Height:", 90, "prop_ta_h"),
        ]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.append(Gtk.Label(label=prop_label, xalign=0))
            adj = Gtk.Adjustment(value=default_val, lower=0, upper=2000, step_increment=1)
            spin = Gtk.SpinButton(adjustment=adj, digits=0)
            spin.set_hexpand(True)
            spin.connect("value-changed",
                         lambda sb, pn=prop_name: self._on_prop_text_area_changed(sb, pn))
            setattr(self, attr_name, spin)
            row.append(spin)
            panel.append(row)

        scrolled.set_child(panel)
        frame.set_child(scrolled)
        return frame

    def _create_text_properties_panel(self):
        """Create the text element properties panel."""
        frame = Gtk.Frame(label="Text Properties")
        frame.set_margin_start(5)
        frame.set_margin_end(5)
        frame.set_margin_bottom(5)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(300)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.set_margin_top(6)
        panel.set_margin_bottom(6)
        panel.set_margin_start(6)
        panel.set_margin_end(6)

        # --- Text Content ---
        text_label = Gtk.Label(label="Text", xalign=0)
        text_label.add_css_class("heading")
        panel.append(text_label)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_min_content_height(60)
        text_scroll.set_max_content_height(100)
        self.text_prop_text = Gtk.TextView()
        self.text_prop_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_prop_text.get_buffer().connect("changed", self._on_text_prop_text_changed)
        text_scroll.set_child(self.text_prop_text)
        panel.append(text_scroll)

        # --- Font ---
        font_label = Gtk.Label(label="Font", xalign=0)
        font_label.add_css_class("heading")
        panel.append(font_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Family:", xalign=0))
        self.text_prop_font = _create_font_combo()
        self.text_prop_font.set_hexpand(True)
        self.text_prop_font.connect("notify::selected", self._on_text_prop_font_changed)
        row.append(self.text_prop_font)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Size:", xalign=0))
        adj = Gtk.Adjustment(value=48, lower=4, upper=500, step_increment=1)
        self.text_prop_font_size = Gtk.SpinButton(adjustment=adj, digits=0)
        self.text_prop_font_size.set_hexpand(True)
        self.text_prop_font_size.connect("value-changed", self._on_text_prop_font_size_changed)
        row.append(self.text_prop_font_size)
        panel.append(row)

        # Line spacing
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Line Spacing:", xalign=0))
        adj = Gtk.Adjustment(value=1.0, lower=0.5, upper=5.0, step_increment=0.1)
        self.text_prop_line_spacing = Gtk.SpinButton(adjustment=adj, digits=1)
        self.text_prop_line_spacing.set_hexpand(True)
        self.text_prop_line_spacing.connect("value-changed", self._on_text_prop_line_spacing_changed)
        row.append(self.text_prop_line_spacing)
        panel.append(row)

        # Bold / Italic
        style_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.text_prop_bold = Gtk.ToggleButton(label="B")
        self.text_prop_bold.connect("toggled", self._on_text_prop_bold_changed)
        style_row.append(self.text_prop_bold)
        self.text_prop_italic = Gtk.ToggleButton(label="I")
        self.text_prop_italic.connect("toggled", self._on_text_prop_italic_changed)
        style_row.append(self.text_prop_italic)
        panel.append(style_row)

        # Text alignment
        align_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        align_row.append(Gtk.Label(label="Align:", xalign=0))
        self.text_prop_align_left = Gtk.ToggleButton(label="L")
        self.text_prop_align_center = Gtk.ToggleButton(label="C")
        self.text_prop_align_right = Gtk.ToggleButton(label="R")
        self.text_prop_align_center.set_active(True)
        for btn in [self.text_prop_align_left, self.text_prop_align_center, self.text_prop_align_right]:
            btn.connect("toggled", self._on_text_prop_align_changed)
            align_row.append(btn)
        panel.append(align_row)

        panel.append(Gtk.Separator())

        # --- Colors ---
        color_label = Gtk.Label(label="Colors", xalign=0)
        color_label.add_css_class("heading")
        panel.append(color_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Fill:", xalign=0))
        self.text_prop_fill_color = Gtk.ColorButton()
        self.text_prop_fill_color.set_rgba(Gdk.RGBA(red=1.0, green=1.0, blue=1.0, alpha=1.0))
        self.text_prop_fill_color.set_hexpand(True)
        self.text_prop_fill_color.connect("color-set", self._on_text_prop_fill_color_changed)
        row.append(self.text_prop_fill_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Outline:", xalign=0))
        self.text_prop_outline_color = Gtk.ColorButton()
        self.text_prop_outline_color.set_rgba(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0))
        self.text_prop_outline_color.set_hexpand(True)
        self.text_prop_outline_color.connect("color-set", self._on_text_prop_outline_color_changed)
        row.append(self.text_prop_outline_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Outline Width:", xalign=0))
        adj = Gtk.Adjustment(value=2, lower=0, upper=20, step_increment=0.5)
        self.text_prop_outline_width = Gtk.SpinButton(adjustment=adj, digits=1)
        self.text_prop_outline_width.set_hexpand(True)
        self.text_prop_outline_width.connect("value-changed", self._on_text_prop_outline_width_changed)
        row.append(self.text_prop_outline_width)
        panel.append(row)

        panel.append(Gtk.Separator())

        # --- Style ---
        style_label = Gtk.Label(label="Style", xalign=0)
        style_label.add_css_class("heading")
        panel.append(style_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Type:", xalign=0))
        self.text_prop_style = Gtk.ComboBoxText()
        self._text_styles = ["normal", "shadow", "outline only", "raised"]
        for s in self._text_styles:
            self.text_prop_style.append_text(s.capitalize())
        self.text_prop_style.set_active(0)
        self.text_prop_style.set_hexpand(True)
        self.text_prop_style.connect("changed", self._on_text_prop_style_changed)
        row.append(self.text_prop_style)
        panel.append(row)

        scrolled.set_child(panel)
        frame.set_child(scrolled)
        return frame

    def _update_properties_panel(self):
        """Show/hide and populate the properties panel based on selection."""
        element = self.selected_elements[0] if self.selected_elements else None

        all_panels = [self.properties_panel, self.text_properties_panel,
                      self.textarea_properties_panel, self.panel_properties_panel]

        if not element or element.type not in (
            ElementType.SPEECH_BUBBLE, ElementType.TEXT, ElementType.TEXTAREA,
            ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL,
        ):
            for p in all_panels:
                p.set_visible(False)
            return

        if element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL):
            for p in all_panels:
                p.set_visible(False)
            self._update_panel_properties_panel(element)
            return

        if element.type == ElementType.TEXT:
            for p in all_panels:
                p.set_visible(False)
            self._update_text_properties_panel(element)
            return

        if element.type == ElementType.TEXTAREA:
            for p in all_panels:
                p.set_visible(False)
            self._update_textarea_properties_panel(element)
            return

        for p in all_panels:
            p.set_visible(False)
        self._updating_properties = True
        self.properties_panel.set_visible(True)

        props = element.properties

        # Body style / tail style (with backward compat for old bubble_type)
        body_style = props.get("body_style") or ("cloud" if props.get("bubble_type") == "thought" else "smooth")
        tail_style = props.get("tail_style") or ("circles" if props.get("bubble_type") == "thought" else "straight")
        if body_style in self._body_styles:
            self.prop_body_style.set_active(self._body_styles.index(body_style))
        if tail_style in self._tail_styles:
            self.prop_tail_style.set_active(self._tail_styles.index(tail_style))

        # Outline
        self.prop_outline_width.set_value(props.get("outline_width", 1.0))

        # Tail circles (only for circles tail style)
        self.prop_tail_circles_row.set_visible(tail_style == "circles")
        if tail_style == "circles":
            self.prop_tail_circles.set_value(props.get("tail_circles", 3))

        # Text
        buf = self.prop_text_view.get_buffer()
        buf.set_text(props.get("text", ""))

        # Font family
        font = props.get("font", "Arial")
        _set_combo_font(self.prop_font_family, font)

        # Font size
        self.prop_font_size.set_value(props.get("font_size", 14))

        # Text color
        rgba = Gdk.RGBA()
        rgba.parse(props.get("text_color", "#000000"))
        self.prop_text_color.set_rgba(rgba)

        # Bold / Italic
        self.prop_bold.set_active(props.get("bold", False))
        self.prop_italic.set_active(props.get("italic", False))

        # Text alignment
        align = props.get("text_align", "center")
        self.prop_align_left.set_active(align == "left")
        self.prop_align_center.set_active(align == "center")
        self.prop_align_right.set_active(align == "right")

        # Text area
        self.prop_ta_x.set_value(props.get("text_area_x", 30))
        self.prop_ta_y.set_value(props.get("text_area_y", 30))
        self.prop_ta_w.set_value(props.get("text_area_width", element.width - 60))
        self.prop_ta_h.set_value(props.get("text_area_height", element.height - 60))

        self._updating_properties = False

    # --- Property change handlers ---

    def _on_prop_body_style_changed(self, combo):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            idx = combo.get_active()
            if 0 <= idx < len(self._body_styles):
                element.properties["body_style"] = self._body_styles[idx]
                self.canvas.queue_draw()

    def _on_prop_tail_style_changed(self, combo):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            idx = combo.get_active()
            if 0 <= idx < len(self._tail_styles):
                element.properties["tail_style"] = self._tail_styles[idx]
                self.prop_tail_circles_row.set_visible(idx == 1)
                self.canvas.queue_draw()

    def _on_prop_outline_width_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties["outline_width"] = spin.get_value()
            self.canvas.queue_draw()

    def _on_prop_text_changed(self, buf):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            element.properties["text"] = buf.get_text(start, end, False)
            self.canvas.queue_draw()

    def _on_prop_font_family_changed(self, combo, pspec=None):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            font = _get_combo_font(combo)
            if font:
                element.properties["font"] = font
                self.canvas.queue_draw()

    def _on_prop_font_size_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties["font_size"] = int(spin.get_value())
            self.canvas.queue_draw()

    def _on_prop_text_color_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            rgba = btn.get_rgba()
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
            element.properties["text_color"] = hex_color
            self.canvas.queue_draw()

    def _on_prop_bold_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties["bold"] = btn.get_active()
            self.canvas.queue_draw()

    def _on_prop_italic_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties["italic"] = btn.get_active()
            self.canvas.queue_draw()

    def _on_prop_text_align_changed(self, btn):
        if self._updating_properties:
            return
        if not btn.get_active():
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            if self.prop_align_left.get_active():
                element.properties["text_align"] = "left"
            elif self.prop_align_right.get_active():
                element.properties["text_align"] = "right"
            else:
                element.properties["text_align"] = "center"
            self.canvas.queue_draw()

    def _on_prop_text_area_changed(self, spin, prop_name):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties[prop_name] = int(spin.get_value())
            self.canvas.queue_draw()

    def _on_prop_tail_circles_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.SPEECH_BUBBLE:
            element.properties["tail_circles"] = int(spin.get_value())
            self.canvas.queue_draw()
    
    def _update_text_properties_panel(self, element):
        """Populate the text properties panel for a TEXT element."""
        self._updating_properties = True
        self.text_properties_panel.set_visible(True)

        props = element.properties

        buf = self.text_prop_text.get_buffer()
        buf.set_text(props.get("text", ""))

        font = props.get("font", "Arial")
        _set_combo_font(self.text_prop_font, font)

        self.text_prop_font_size.set_value(props.get("font_size", 48))
        self.text_prop_line_spacing.set_value(props.get("line_spacing", 1.0))
        self.text_prop_bold.set_active(props.get("bold", False))
        self.text_prop_italic.set_active(props.get("italic", False))

        text_align = props.get("text_align", "center")
        self.text_prop_align_left.set_active(text_align == "left")
        self.text_prop_align_center.set_active(text_align == "center")
        self.text_prop_align_right.set_active(text_align == "right")

        fill_color = props.get("fill_color", "#FFFFFF")
        fr, fg, fb = self._hex_to_rgb(fill_color)
        self.text_prop_fill_color.set_rgba(Gdk.RGBA(red=fr, green=fg, blue=fb, alpha=1.0))

        outline_color = props.get("outline_color", "#000000")
        or_, og, ob = self._hex_to_rgb(outline_color)
        self.text_prop_outline_color.set_rgba(Gdk.RGBA(red=or_, green=og, blue=ob, alpha=1.0))

        self.text_prop_outline_width.set_value(props.get("outline_width", 2))

        style = props.get("text_style", "normal")
        if style in self._text_styles:
            self.text_prop_style.set_active(self._text_styles.index(style))

        self._updating_properties = False

    def _on_text_prop_text_changed(self, buf):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["text"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            self.canvas.queue_draw()

    def _on_text_prop_font_changed(self, combo, pspec=None):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["font"] = _get_combo_font(combo)
            self.canvas.queue_draw()

    def _on_text_prop_font_size_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["font_size"] = int(spin.get_value())
            self.canvas.queue_draw()

    def _on_text_prop_line_spacing_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["line_spacing"] = spin.get_value()
            self.canvas.queue_draw()

    def _on_text_prop_bold_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["bold"] = btn.get_active()
            self.canvas.queue_draw()

    def _on_text_prop_italic_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["italic"] = btn.get_active()
            self.canvas.queue_draw()

    def _on_text_prop_align_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            if self.text_prop_align_left.get_active():
                element.properties["text_align"] = "left"
            elif self.text_prop_align_right.get_active():
                element.properties["text_align"] = "right"
            else:
                element.properties["text_align"] = "center"
            self.canvas.queue_draw()

    def _on_text_prop_fill_color_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            rgba = btn.get_rgba()
            element.properties["fill_color"] = "#{:02x}{:02x}{:02x}".format(
                int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
            self.canvas.queue_draw()

    def _on_text_prop_outline_color_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            rgba = btn.get_rgba()
            element.properties["outline_color"] = "#{:02x}{:02x}{:02x}".format(
                int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
            self.canvas.queue_draw()

    def _on_text_prop_outline_width_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            element.properties["outline_width"] = spin.get_value()
            self.canvas.queue_draw()

    def _on_text_prop_style_changed(self, combo):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXT:
            idx = combo.get_active()
            if 0 <= idx < len(self._text_styles):
                element.properties["text_style"] = self._text_styles[idx]
            self.canvas.queue_draw()

    def _create_textarea_properties_panel(self):
        """Create the text area properties panel."""
        frame = Gtk.Frame(label="Text Area Properties")
        frame.set_margin_start(5)
        frame.set_margin_end(5)
        frame.set_margin_bottom(5)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(300)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.set_margin_top(6)
        panel.set_margin_bottom(6)
        panel.set_margin_start(6)
        panel.set_margin_end(6)

        # --- Text Content ---
        text_label = Gtk.Label(label="Text", xalign=0)
        text_label.add_css_class("heading")
        panel.append(text_label)

        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_min_content_height(60)
        text_scroll.set_max_content_height(120)
        self.ta_prop_text = Gtk.TextView()
        self.ta_prop_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.ta_prop_text.get_buffer().connect("changed", self._on_ta_prop_changed, "text")
        text_scroll.set_child(self.ta_prop_text)
        panel.append(text_scroll)

        panel.append(Gtk.Separator())

        # --- Font ---
        font_label = Gtk.Label(label="Font", xalign=0)
        font_label.add_css_class("heading")
        panel.append(font_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Family:", xalign=0))
        self.ta_prop_font = _create_font_combo()
        self.ta_prop_font.set_hexpand(True)
        self.ta_prop_font.connect("notify::selected", self._on_ta_prop_font_changed)
        row.append(self.ta_prop_font)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Size:", xalign=0))
        adj = Gtk.Adjustment(value=16, lower=4, upper=200, step_increment=1)
        self.ta_prop_font_size = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_font_size.set_hexpand(True)
        self.ta_prop_font_size.connect("value-changed", self._on_ta_prop_spin_changed, "font_size")
        row.append(self.ta_prop_font_size)
        panel.append(row)

        # Line spacing
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Line Spacing:", xalign=0))
        adj = Gtk.Adjustment(value=1.0, lower=0.5, upper=5.0, step_increment=0.1)
        self.ta_prop_line_spacing = Gtk.SpinButton(adjustment=adj, digits=1)
        self.ta_prop_line_spacing.set_hexpand(True)
        self.ta_prop_line_spacing.connect("value-changed", self._on_ta_prop_spin_changed, "line_spacing")
        row.append(self.ta_prop_line_spacing)
        panel.append(row)

        # Bold / Italic
        style_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.ta_prop_bold = Gtk.ToggleButton(label="B")
        self.ta_prop_bold.connect("toggled", self._on_ta_prop_toggle_changed, "bold")
        style_row.append(self.ta_prop_bold)
        self.ta_prop_italic = Gtk.ToggleButton(label="I")
        self.ta_prop_italic.connect("toggled", self._on_ta_prop_toggle_changed, "italic")
        style_row.append(self.ta_prop_italic)
        panel.append(style_row)

        # Text alignment
        align_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        align_row.append(Gtk.Label(label="Align:", xalign=0))
        self.ta_prop_align_left = Gtk.ToggleButton(label="L")
        self.ta_prop_align_center = Gtk.ToggleButton(label="C")
        self.ta_prop_align_right = Gtk.ToggleButton(label="R")
        self.ta_prop_align_center.set_active(True)
        for btn in [self.ta_prop_align_left, self.ta_prop_align_center, self.ta_prop_align_right]:
            btn.connect("toggled", self._on_ta_prop_align_changed)
            align_row.append(btn)
        panel.append(align_row)

        panel.append(Gtk.Separator())

        # --- Colors ---
        color_label = Gtk.Label(label="Colors", xalign=0)
        color_label.add_css_class("heading")
        panel.append(color_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Text:", xalign=0))
        self.ta_prop_text_color = Gtk.ColorButton()
        self.ta_prop_text_color.set_rgba(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0))
        self.ta_prop_text_color.set_hexpand(True)
        self.ta_prop_text_color.connect("color-set", self._on_ta_prop_color_changed, "text_color")
        row.append(self.ta_prop_text_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Background:", xalign=0))
        self.ta_prop_bg_color = Gtk.ColorButton()
        self.ta_prop_bg_color.set_rgba(Gdk.RGBA(red=1.0, green=1.0, blue=1.0, alpha=1.0))
        self.ta_prop_bg_color.set_hexpand(True)
        self.ta_prop_bg_color.connect("color-set", self._on_ta_prop_color_changed, "background_color")
        row.append(self.ta_prop_bg_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Padding:", xalign=0))
        adj = Gtk.Adjustment(value=10, lower=0, upper=100, step_increment=1)
        self.ta_prop_padding = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_padding.set_hexpand(True)
        self.ta_prop_padding.connect("value-changed", self._on_ta_prop_spin_changed, "padding")
        row.append(self.ta_prop_padding)
        panel.append(row)

        panel.append(Gtk.Separator())

        # --- Border ---
        border_label = Gtk.Label(label="Border", xalign=0)
        border_label.add_css_class("heading")
        panel.append(border_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Width:", xalign=0))
        adj = Gtk.Adjustment(value=1, lower=0, upper=20, step_increment=0.5)
        self.ta_prop_border_width = Gtk.SpinButton(adjustment=adj, digits=1)
        self.ta_prop_border_width.set_hexpand(True)
        self.ta_prop_border_width.connect("value-changed", self._on_ta_prop_spin_changed, "border_width")
        row.append(self.ta_prop_border_width)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Color:", xalign=0))
        self.ta_prop_border_color = Gtk.ColorButton()
        self.ta_prop_border_color.set_rgba(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0))
        self.ta_prop_border_color.set_hexpand(True)
        self.ta_prop_border_color.connect("color-set", self._on_ta_prop_color_changed, "border_color")
        row.append(self.ta_prop_border_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Radius:", xalign=0))
        adj = Gtk.Adjustment(value=0, lower=0, upper=50, step_increment=1)
        self.ta_prop_border_radius = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_border_radius.set_hexpand(True)
        self.ta_prop_border_radius.connect("value-changed", self._on_ta_prop_spin_changed, "border_radius")
        row.append(self.ta_prop_border_radius)
        panel.append(row)

        panel.append(Gtk.Separator())

        # --- Drop Shadow ---
        shadow_label = Gtk.Label(label="Drop Shadow", xalign=0)
        shadow_label.add_css_class("heading")
        panel.append(shadow_label)

        self.ta_prop_shadow_enabled = Gtk.CheckButton(label="Enabled")
        self.ta_prop_shadow_enabled.connect("toggled", self._on_ta_prop_toggle_changed, "shadow_enabled")
        panel.append(self.ta_prop_shadow_enabled)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Color:", xalign=0))
        self.ta_prop_shadow_color = Gtk.ColorButton()
        self.ta_prop_shadow_color.set_rgba(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.25))
        self.ta_prop_shadow_color.set_hexpand(True)
        self.ta_prop_shadow_color.connect("color-set", self._on_ta_prop_color_changed, "shadow_color")
        row.append(self.ta_prop_shadow_color)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Offset X:", xalign=0))
        adj = Gtk.Adjustment(value=4, lower=-30, upper=30, step_increment=1)
        self.ta_prop_shadow_x = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_shadow_x.set_hexpand(True)
        self.ta_prop_shadow_x.connect("value-changed", self._on_ta_prop_spin_changed, "shadow_offset_x")
        row.append(self.ta_prop_shadow_x)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Offset Y:", xalign=0))
        adj = Gtk.Adjustment(value=4, lower=-30, upper=30, step_increment=1)
        self.ta_prop_shadow_y = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_shadow_y.set_hexpand(True)
        self.ta_prop_shadow_y.connect("value-changed", self._on_ta_prop_spin_changed, "shadow_offset_y")
        row.append(self.ta_prop_shadow_y)
        panel.append(row)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Blur:", xalign=0))
        adj = Gtk.Adjustment(value=0, lower=0, upper=30, step_increment=1)
        self.ta_prop_shadow_blur = Gtk.SpinButton(adjustment=adj, digits=0)
        self.ta_prop_shadow_blur.set_hexpand(True)
        self.ta_prop_shadow_blur.connect("value-changed", self._on_ta_prop_spin_changed, "shadow_blur")
        row.append(self.ta_prop_shadow_blur)
        panel.append(row)

        scrolled.set_child(panel)
        frame.set_child(scrolled)
        return frame

    def _update_textarea_properties_panel(self, element):
        """Populate the textarea properties panel."""
        self._updating_properties = True
        self.textarea_properties_panel.set_visible(True)

        props = element.properties

        buf = self.ta_prop_text.get_buffer()
        buf.set_text(props.get("text", ""))

        font = props.get("font", "Arial")
        _set_combo_font(self.ta_prop_font, font)

        self.ta_prop_font_size.set_value(props.get("font_size", 16))
        self.ta_prop_line_spacing.set_value(props.get("line_spacing", 1.0))
        self.ta_prop_bold.set_active(props.get("bold", False))
        self.ta_prop_italic.set_active(props.get("italic", False))

        text_align = props.get("text_align", "left")
        self.ta_prop_align_left.set_active(text_align == "left")
        self.ta_prop_align_center.set_active(text_align == "center")
        self.ta_prop_align_right.set_active(text_align == "right")

        tc = props.get("text_color", "#000000")
        tr, tg, tb = self._hex_to_rgb(tc)
        self.ta_prop_text_color.set_rgba(Gdk.RGBA(red=tr, green=tg, blue=tb, alpha=1.0))

        bg = props.get("background_color", "#FFFFFF")
        br, bgg, bb = self._hex_to_rgb(bg)
        self.ta_prop_bg_color.set_rgba(Gdk.RGBA(red=br, green=bgg, blue=bb, alpha=1.0))

        self.ta_prop_padding.set_value(props.get("padding", 10))

        self.ta_prop_border_width.set_value(props.get("border_width", 1))

        bc = props.get("border_color", "#000000")
        bcr, bcg, bcb = self._hex_to_rgb(bc)
        self.ta_prop_border_color.set_rgba(Gdk.RGBA(red=bcr, green=bcg, blue=bcb, alpha=1.0))

        self.ta_prop_border_radius.set_value(props.get("border_radius", 0))

        self.ta_prop_shadow_enabled.set_active(props.get("shadow_enabled", False))
        self.ta_prop_shadow_x.set_value(props.get("shadow_offset_x", 4))
        self.ta_prop_shadow_y.set_value(props.get("shadow_offset_y", 4))
        self.ta_prop_shadow_blur.set_value(props.get("shadow_blur", 0))

        sc = props.get("shadow_color", "#00000040")
        # Parse shadow color (may have alpha as hex)
        if len(sc) == 9:  # #RRGGBBAA
            sr, sg, sb = self._hex_to_rgb(sc[:7])
            sa = int(sc[7:9], 16) / 255.0
        else:
            sr, sg, sb = self._hex_to_rgb(sc)
            sa = 0.25
        self.ta_prop_shadow_color.set_rgba(Gdk.RGBA(red=sr, green=sg, blue=sb, alpha=sa))

        self._updating_properties = False

    # --- Textarea property change handlers ---

    def _on_ta_prop_changed(self, buf, prop_name):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            element.properties[prop_name] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            self.canvas.queue_draw()

    def _on_ta_prop_font_changed(self, combo, pspec=None):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            element.properties["font"] = _get_combo_font(combo)
            self.canvas.queue_draw()

    def _on_ta_prop_spin_changed(self, spin, prop_name):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            element.properties[prop_name] = spin.get_value()
            self.canvas.queue_draw()

    def _on_ta_prop_toggle_changed(self, btn, prop_name):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            element.properties[prop_name] = btn.get_active()
            self.canvas.queue_draw()

    def _on_ta_prop_align_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            if self.ta_prop_align_left.get_active():
                element.properties["text_align"] = "left"
            elif self.ta_prop_align_right.get_active():
                element.properties["text_align"] = "right"
            else:
                element.properties["text_align"] = "center"
            self.canvas.queue_draw()

    def _on_ta_prop_color_changed(self, btn, prop_name):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type == ElementType.TEXTAREA:
            rgba = btn.get_rgba()
            if prop_name == "shadow_color":
                element.properties[prop_name] = "#{:02x}{:02x}{:02x}{:02x}".format(
                    int(rgba.red * 255), int(rgba.green * 255),
                    int(rgba.blue * 255), int(rgba.alpha * 255))
            else:
                element.properties[prop_name] = "#{:02x}{:02x}{:02x}".format(
                    int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
            self.canvas.queue_draw()

    def _create_panel_properties_panel(self):
        """Create the panel properties panel for Rect Panel/Circle Panel."""
        frame = Gtk.Frame(label="Panel Properties")
        frame.set_margin_start(5)
        frame.set_margin_end(5)
        frame.set_margin_bottom(5)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.set_margin_start(8)
        panel.set_margin_end(8)
        panel.set_margin_top(8)
        panel.set_margin_bottom(8)

        # Outline enable toggle
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Outline:", xalign=0))
        self.panel_prop_outline_enabled = Gtk.CheckButton(label="Enabled")
        self.panel_prop_outline_enabled.set_active(True)
        self.panel_prop_outline_enabled.connect("toggled", self._on_panel_prop_outline_toggled)
        row.append(self.panel_prop_outline_enabled)
        panel.append(row)

        # Outline width
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Width:", xalign=0))
        adj = Gtk.Adjustment(value=2, lower=0.5, upper=20, step_increment=0.5)
        self.panel_prop_border_width = Gtk.SpinButton(adjustment=adj, digits=1)
        self.panel_prop_border_width.set_hexpand(True)
        self.panel_prop_border_width.connect("value-changed", self._on_panel_prop_border_width_changed)
        row.append(self.panel_prop_border_width)
        panel.append(row)

        # Outline color
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(Gtk.Label(label="Color:", xalign=0))
        self.panel_prop_border_color = Gtk.ColorButton()
        self.panel_prop_border_color.set_rgba(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0))
        self.panel_prop_border_color.set_hexpand(True)
        self.panel_prop_border_color.connect("color-set", self._on_panel_prop_border_color_changed)
        row.append(self.panel_prop_border_color)
        panel.append(row)

        frame.set_child(panel)
        return frame

    def _update_panel_properties_panel(self, element):
        """Populate the panel properties panel from element properties."""
        self._updating_properties = True
        self.panel_properties_panel.set_visible(True)

        props = element.properties
        outline_enabled = props.get("outline_enabled", True)
        self.panel_prop_outline_enabled.set_active(outline_enabled)
        self.panel_prop_border_width.set_value(props.get("border_width", 2))
        self.panel_prop_border_width.set_sensitive(outline_enabled)
        self.panel_prop_border_color.set_sensitive(outline_enabled)

        rgba = Gdk.RGBA()
        rgba.parse(props.get("border_color", "#000000"))
        self.panel_prop_border_color.set_rgba(rgba)

        self._updating_properties = False

    def _on_panel_prop_outline_toggled(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL):
            enabled = btn.get_active()
            element.properties["outline_enabled"] = enabled
            self.panel_prop_border_width.set_sensitive(enabled)
            self.panel_prop_border_color.set_sensitive(enabled)
            self.canvas.queue_draw()

    def _on_panel_prop_border_width_changed(self, spin):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL):
            element.properties["border_width"] = spin.get_value()
            self.canvas.queue_draw()

    def _on_panel_prop_border_color_changed(self, btn):
        if self._updating_properties:
            return
        element = self.selected_elements[0] if self.selected_elements else None
        if element and element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL):
            rgba = btn.get_rgba()
            element.properties["border_color"] = "#{:02x}{:02x}{:02x}".format(
                int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))
            self.canvas.queue_draw()

    # --- Image Library ---

    def _create_image_library_panel(self):
        """Create the image library panel."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.set_size_request(250, -1)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(8)

        title = Gtk.Label(label="Image Library")
        title.add_css_class("heading")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)

        delete_btn = Gtk.Button(label="Delete Unused")
        delete_btn.set_tooltip_text("Delete all images not used in any page")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._on_delete_unused_images)
        header.append(delete_btn)

        box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.image_lib_flow = Gtk.FlowBox()
        self.image_lib_flow.set_valign(Gtk.Align.START)
        self.image_lib_flow.set_max_children_per_line(3)
        self.image_lib_flow.set_min_children_per_line(1)
        self.image_lib_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.image_lib_flow.set_homogeneous(True)
        self.image_lib_flow.set_column_spacing(6)
        self.image_lib_flow.set_row_spacing(6)
        self.image_lib_flow.set_margin_start(8)
        self.image_lib_flow.set_margin_end(8)
        self.image_lib_flow.set_margin_bottom(8)

        scrolled.set_child(self.image_lib_flow)
        box.append(scrolled)

        return box

    def _get_used_image_filenames(self):
        """Get set of image filenames used across all pages."""
        used = set()
        for page in self.project.pages:
            for element in page.elements:
                img = element.properties.get("image")
                if img:
                    used.add(img)
        return used

    def _refresh_image_library(self):
        """Reload the image library with lazy-loaded thumbnails."""
        # Cancel any pending lazy-load
        self._image_lib_load_queue = []

        # Clear existing children
        while True:
            child = self.image_lib_flow.get_first_child()
            if child is None:
                break
            self.image_lib_flow.remove(child)

        if not self.project.images_dir.exists():
            return

        # Apply CSS once
        if not getattr(self, '_image_lib_css_applied', False):
            css_provider = Gtk.CssProvider()
            css_provider.load_from_string(
                ".image-lib-used { border: 3px solid #22cc22; }"
                ".image-lib-unused { border: 1px solid #999999; }"
            )
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            self._image_lib_css_applied = True

        used = self._get_used_image_filenames()
        valid_ext = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}

        # Build list of items with placeholders, queue lazy image loading
        load_queue = []
        for img_path in sorted(self.project.images_dir.iterdir()):
            if img_path.suffix.lower() not in valid_ext:
                continue
            filename = img_path.name
            is_used = filename in used

            item_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            # Placeholder spinner until image loads
            spinner = Gtk.Spinner()
            spinner.set_size_request(100, 100)
            spinner.start()

            thumb_frame = Gtk.Frame()
            thumb_frame.set_child(spinner)
            if is_used:
                thumb_frame.add_css_class("image-lib-used")
            else:
                thumb_frame.add_css_class("image-lib-unused")
            item_box.append(thumb_frame)

            # Filename label
            display_name = filename if len(filename) <= 14 else filename[:11] + "..."
            name_label = Gtk.Label(label=display_name)
            name_label.set_tooltip_text(filename)
            name_label.set_ellipsize(3)
            item_box.append(name_label)

            # Drag source
            drag_source = Gtk.DragSource.new()
            drag_source.set_actions(Gdk.DragAction.COPY)
            drag_source.connect("prepare", self._on_image_lib_drag_prepare, filename)
            item_box.add_controller(drag_source)

            self.image_lib_flow.append(item_box)
            load_queue.append((thumb_frame, str(img_path)))

        # Lazy load images in batches via idle callback
        self._image_lib_load_queue = load_queue
        if load_queue:
            GLib.idle_add(self._image_lib_load_next)

    def _image_lib_load_next(self):
        """Load next batch of image library thumbnails."""
        batch_size = 4
        for _ in range(batch_size):
            if not self._image_lib_load_queue:
                return False  # Done, remove idle source
            thumb_frame, img_path_str = self._image_lib_load_queue.pop(0)
            try:
                # Check widget is still alive
                if not thumb_frame.get_parent():
                    continue
                picture = Gtk.Picture.new_for_filename(img_path_str)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                picture.set_size_request(100, 100)
                thumb_frame.set_child(picture)
            except Exception:
                label = Gtk.Label(label="?")
                label.set_size_request(100, 100)
                thumb_frame.set_child(label)
        return True  # Continue loading

    def _on_image_lib_drag_prepare(self, source, x, y, filename):
        """Prepare drag data for image library item."""
        content = Gdk.ContentProvider.new_for_value(f"image_lib:{filename}")
        return content

    def _on_toggle_image_library(self, btn):
        """Show/hide the image library panel."""
        visible = btn.get_active()
        self.image_library_panel.set_visible(visible)
        if visible:
            self._refresh_image_library()

    def _on_delete_unused_images(self, btn):
        """Delete images not used in any page."""
        if not self.project.images_dir.exists():
            return
        used = self._get_used_image_filenames()
        valid_ext = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}
        deleted = 0
        for img_path in list(self.project.images_dir.iterdir()):
            if img_path.suffix.lower() in valid_ext and img_path.name not in used:
                img_path.unlink()
                deleted += 1
        if deleted > 0:
            # Clear image cache entries for deleted files
            keys_to_remove = [k for k in self.image_cache if k[0] not in used]
            for key in keys_to_remove:
                del self.image_cache[key]
        self._refresh_image_library()

    def _handle_image_lib_drop(self, image_filename, x, y):
        """Handle drop of an image from the library onto the canvas (no copy needed)."""
        scale = self.zoom_level / 100.0
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y

        page_x = (x - x_offset) / scale
        page_y = (y - y_offset) / scale

        if page_x < 0 or page_x > self.current_page.width or page_y < 0 or page_y > self.current_page.height:
            return True

        # Check if dropped on an existing panel
        target_panel = None
        for element in reversed(self.current_page.elements):
            if (element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL) and
                element.x <= page_x <= element.x + element.width and
                element.y <= page_y <= element.y + element.height):
                target_panel = element
                break

        if target_panel:
            # Clear old cached surface for previous image
            old_img = target_panel.properties.get("image")
            if old_img:
                keys_to_remove = [k for k in self.image_cache if k[0] == old_img]
                for key in keys_to_remove:
                    del self.image_cache[key]

            target_panel.properties["image"] = image_filename
            # Clear cached dimensions so they get recalculated on next draw
            for key in ["image_width", "image_height", "image_offset_x", "image_offset_y"]:
                target_panel.properties.pop(key, None)

        self.canvas.queue_draw()
        if self.image_library_panel.get_visible():
            self._refresh_image_library()
        return True

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

            # Draw gridlines on top of elements
            if self.gridlines_visible:
                self._draw_gridlines(cr, x_offset, y_offset, page_width, page_height, scale)

    def _draw_gridlines(self, cr, x_offset, y_offset, page_width, page_height, scale):
        """Draw horizontal and vertical gridlines."""
        if not self.current_page:
            return

        cr.save()
        cr.set_source_rgba(1.0, 0.0, 0.0, 0.7)
        cr.set_line_width(1)
        cr.set_dash([6, 4])

        # Horizontal gridlines
        for gy in self.project.gridlines_h:
            y = y_offset + gy * scale
            cr.move_to(x_offset, y)
            cr.line_to(x_offset + page_width, y)
            cr.stroke()

        # Vertical gridlines
        for gx in self.project.gridlines_v:
            x = x_offset + gx * scale
            cr.move_to(x, y_offset)
            cr.line_to(x, y_offset + page_height)
            cr.stroke()

        cr.restore()

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

                # Use temp dimensions during resize for real-time preview
                if (self.resizing_image and self.resizing_element == element):
                    render_width = self.temp_image_width
                    render_height = self.temp_image_height
                else:
                    render_width = stored_image_width
                    render_height = stored_image_height

                # Use stored offset (in page coordinates)
                stored_offset_x = element.properties.get("image_offset_x", (element.width - stored_image_width) / 2)
                stored_offset_y = element.properties.get("image_offset_y", (element.height - stored_image_height) / 2)

                # Calculate scaled positions
                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                display_width = render_width * scale
                display_height = render_height * scale

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
            if element.properties.get("outline_enabled", True):
                border_w = element.properties.get("border_width", 2)
                border_r, border_g, border_b = self._hex_to_rgb(border_color)
                cr.set_source_rgb(border_r, border_g, border_b)
                cr.set_line_width(border_w)
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

                # Use temp dimensions during resize for real-time preview
                if (self.resizing_image and self.resizing_element == element):
                    render_width = self.temp_image_width
                    render_height = self.temp_image_height
                else:
                    render_width = stored_image_width
                    render_height = stored_image_height

                # Calculate scaled positions
                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                display_width = render_width * scale
                display_height = render_height * scale

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
            if element.properties.get("outline_enabled", True):
                border_w = element.properties.get("border_width", 2)
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
                cr.set_line_width(border_w)
                cr.stroke()

        elif element.type == ElementType.CIRCLE_PANEL:
            # Draw circle/ellipse panel
            border_color = element.properties.get("border_color", "#000000")
            bg_color = element.properties.get("background_color", "#FFFFFF")
            image_filename = element.properties.get("image")

            cx = x + w / 2
            cy = y + h / 2
            rx = w / 2
            ry = h / 2

            import math

            if image_filename:
                # Initialize image dimensions if not set
                if "image_width" not in element.properties or "image_height" not in element.properties:
                    from PIL import Image
                    image_path = self.project.images_dir / image_filename
                    if image_path.exists():
                        pil_image = Image.open(str(image_path))
                        img_width, img_height = pil_image.size

                        panel_w = element.width
                        panel_h = element.height
                        scale_x_img = panel_w / img_width
                        scale_y_img = panel_h / img_height
                        scale_factor = min(scale_x_img, scale_y_img)

                        element.properties["image_width"] = img_width * scale_factor
                        element.properties["image_height"] = img_height * scale_factor
                        element.properties["image_offset_x"] = (panel_w - img_width * scale_factor) / 2
                        element.properties["image_offset_y"] = (panel_h - img_height * scale_factor) / 2

                stored_image_width = element.properties.get("image_width", element.width)
                stored_image_height = element.properties.get("image_height", element.height)
                stored_offset_x = element.properties.get("image_offset_x", 0)
                stored_offset_y = element.properties.get("image_offset_y", 0)

                # Use temp dimensions during resize for real-time preview
                if (self.resizing_image and self.resizing_element == element):
                    render_width = self.temp_image_width
                    render_height = self.temp_image_height
                else:
                    render_width = stored_image_width
                    render_height = stored_image_height

                img_x = x + stored_offset_x * scale
                img_y = y + stored_offset_y * scale
                display_width = render_width * scale
                display_height = render_height * scale

                surface = self._get_cached_image_surface(image_filename, int(stored_image_width), int(stored_image_height))

                if surface:
                    cr.save()
                    # Elliptical clipping path
                    cr.new_path()
                    cr.save()
                    cr.translate(cx, cy)
                    cr.scale(rx, ry)
                    cr.arc(0, 0, 1, 0, 2 * math.pi)
                    cr.restore()
                    cr.clip()

                    cr.translate(img_x, img_y)
                    if surface.get_width() > 0 and surface.get_height() > 0:
                        sx = display_width / surface.get_width()
                        sy = display_height / surface.get_height()
                        cr.scale(sx, sy)
                    cr.set_source_surface(surface, 0, 0)
                    cr.paint()
                    cr.restore()
                else:
                    cr.save()
                    cr.new_path()
                    cr.save()
                    cr.translate(cx, cy)
                    cr.scale(rx, ry)
                    cr.arc(0, 0, 1, 0, 2 * math.pi)
                    cr.restore()
                    cr.clip_preserve()
                    self._draw_panel_pattern_in_path(cr, x, y, w, h, bg_color, scale)
                    cr.restore()
            else:
                # No image, draw dithered pattern inside ellipse
                cr.save()
                cr.new_path()
                cr.save()
                cr.translate(cx, cy)
                cr.scale(rx, ry)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.clip_preserve()
                self._draw_panel_pattern_in_path(cr, x, y, w, h, bg_color, scale)
                cr.restore()

            # Draw elliptical border
            if element.properties.get("outline_enabled", True):
                border_w = element.properties.get("border_width", 2)
                cr.new_path()
                cr.save()
                cr.translate(cx, cy)
                cr.scale(rx, ry)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                border_r, border_g, border_b = self._hex_to_rgb(border_color)
                cr.set_source_rgb(border_r, border_g, border_b)
                cr.set_line_width(border_w)
                cr.stroke()

        else:
            # Draw other element types (shapes, text, etc.)
            self._draw_other_elements(cr, element, x, y, w, h, scale)
        
        # Draw selection if selected (TEXT and TEXTAREA draw their own in _draw_rotated_element)
        if element in self.selected_elements and element.type not in (ElementType.TEXT, ElementType.TEXTAREA):
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
            
            elif self.selection_mode == 'image' and (element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and element.properties.get("image"):
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
        
        elif element.type == ElementType.TEXT:
            # Draw title/large text element
            self._draw_rotated_element(cr, element, x, y, w, h, scale,
                                       self._draw_text_element)

        elif element.type == ElementType.TEXTAREA:
            self._draw_rotated_element(cr, element, x, y, w, h, scale,
                                       self._draw_textarea_element)
        
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
            
            if control_points:
                # Spline-based unified bubble
                scaled_points = [(x + px * w / element.width, y + py * h / element.height)
                                for px, py in control_points]

                tail_base_t = element.properties.get("tail_base_t", 0.75)
                tail_tip_x = element.properties.get("tail_tip_x", w / 2)
                tail_tip_y = element.properties.get("tail_tip_y", h + 50)
                tail_tip_x_scaled = x + (tail_tip_x * w / element.width)
                tail_tip_y_scaled = y + (tail_tip_y * h / element.height)

                segments = self._get_bubble_curve_segments(scaled_points)
                n = len(segments)
                outline_width = element.properties.get("outline_width", 1.0)

                # Resolve body_style and tail_style with backward compat
                body_style = element.properties.get("body_style") or (
                    "cloud" if element.properties.get("bubble_type") == "thought" else "smooth")
                tail_style = element.properties.get("tail_style") or (
                    "circles" if element.properties.get("bubble_type") == "thought" else "straight")

                # --- DRAW BODY + TAIL ---
                if tail_style == "straight":
                    # Straight tail: integrate triangle into the body path
                    self._draw_bubble_body_with_straight_tail(
                        cr, segments, n, scaled_points, tail_base_t,
                        tail_tip_x_scaled, tail_tip_y_scaled,
                        element.properties.get("tail_base_width", 30) * scale,
                        w, h, outline_width, body_style)
                elif tail_style == "jagged":
                    # Jagged tail: zigzag edges from bubble to tip
                    self._draw_bubble_body_with_jagged_tail(
                        cr, segments, n, scaled_points, tail_base_t,
                        tail_tip_x_scaled, tail_tip_y_scaled,
                        element.properties.get("tail_base_width", 30) * scale,
                        w, h, outline_width, body_style)
                else:
                    # Circle tail: draw closed body, then circles separately
                    self._draw_bubble_closed_body(cr, segments, outline_width, body_style)
                    # Draw circle chain
                    tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)
                    num_circles = element.properties.get("tail_circles", 3)
                    max_radius = 10 * scale
                    min_radius = 3 * scale
                    for i in range(num_circles):
                        t = (i + 0.8) / (num_circles + 0.2)
                        cx_c = tail_base_pos[0] + t * (tail_tip_x_scaled - tail_base_pos[0])
                        cy_c = tail_base_pos[1] + t * (tail_tip_y_scaled - tail_base_pos[1])
                        radius = max_radius - (max_radius - min_radius) * i / max(num_circles - 1, 1)
                        cr.set_source_rgb(1, 1, 1)
                        cr.arc(cx_c, cy_c, radius, 0, 2 * math.pi)
                        cr.fill_preserve()
                        cr.set_source_rgb(0, 0, 0)
                        cr.set_line_width(outline_width)
                        cr.stroke()

                # Draw text
                self._draw_bubble_text(cr, element, x, y, w, h, text, text_color)

                # Draw handles if selected
                if element in self.selected_elements:
                    handle_size = 8
                    tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)

                    cr.set_source_rgb(1.0, 0.08, 0.58)
                    cr.arc(tail_tip_x_scaled, tail_tip_y_scaled, handle_size / 2, 0, 2 * math.pi)
                    cr.fill()

                    cr.set_source_rgb(1.0, 0.08, 0.58)
                    cr.arc(tail_base_pos[0], tail_base_pos[1], handle_size / 2, 0, 2 * math.pi)
                    cr.fill()

                    if element == self.edit_mode_element:
                        cr.set_source_rgb(0.0, 0.8, 0.0)
                        for px, py in scaled_points:
                            cr.arc(px, py, handle_size / 2, 0, 2 * math.pi)
                            cr.fill()
            
            else:
                # Old-style bubble rendering (for bubbles without control_points)
                tail_tip_x = element.properties.get("tail_tip_x", 70)
                tail_tip_y = element.properties.get("tail_tip_y", 200)
                tail_tip_x_scaled = x + (tail_tip_x * w / element.width)
                tail_tip_y_scaled = y + (tail_tip_y * h / element.height)
                tail_base_width = element.properties.get("tail_base_width", 30)
                tail_base_width_scaled = tail_base_width * scale

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
                    outline_width = element.properties.get("outline_width", 1.0)
                    cr.set_line_width(outline_width)
                    cr.stroke()

                elif bubble_type == "thought":
                    # Draw thought bubble tail as decreasing circles
                    bubble_center_x = x + w / 2
                    bubble_center_y = y + h / 2
                    outline_width = element.properties.get("outline_width", 1.0)

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
                        cr.set_line_width(outline_width)
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
                outline_width = element.properties.get("outline_width", 1.0)
                cr.set_line_width(outline_width)
                cr.save()
                cr.translate(x + w/2, y + h/2)
                cr.scale(w/2, h/2)
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.stroke()

                # Draw text using PangoCairo for word wrapping
                self._draw_bubble_text(cr, element, x, y, w, h, text, text_color)
                
                # Draw tail tip handle if selected
                if element in self.selected_elements:
                    handle_size = 8
                    cr.set_source_rgb(0.0, 0.8, 0.0)  # Green for tail tip handle
                    cr.arc(tail_tip_x_scaled, tail_tip_y_scaled, handle_size / 2, 0, 2 * math.pi)
                    cr.fill()
    
    # --- Bubble body style drawing helpers ---

    def _sample_segments(self, segments, num_samples):
        """Sample evenly-spaced points along Bézier segments."""
        points = []
        n = len(segments)
        for i in range(num_samples):
            t = i / num_samples
            seg_t = t * n
            seg_idx = int(seg_t) % n
            local_t = seg_t - int(seg_t)
            seg = segments[seg_idx]
            points.append(self._eval_bezier_point(seg[0], seg[1], seg[2], seg[3], local_t))
        return points

    def _compute_center(self, points):
        """Compute centroid of a list of points."""
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        return (cx, cy)

    def _compute_jagged_points(self, points, center, outline_width):
        """Displace points alternately outward/inward to create a starburst/zigzag."""
        import math
        spike_height = max(8, outline_width * 3)
        jagged = []
        for i, (px, py) in enumerate(points):
            dx = px - center[0]
            dy = py - center[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 0:
                nx, ny = dx / dist, dy / dist
            else:
                nx, ny = 0, 0
            if i % 2 == 0:
                jagged.append((px + nx * spike_height, py + ny * spike_height))
            else:
                jagged.append((px - nx * spike_height * 0.3, py - ny * spike_height * 0.3))
        return jagged

    def _build_cloud_path(self, cr, points, center, closed=True):
        """Build a scalloped/cloud path on the cairo context from sample points."""
        import math
        n = len(points)
        cr.new_path()
        end = n if closed else n - 1
        for i in range(end):
            p1 = points[i]
            p2 = points[(i + 1) % n]
            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2
            dx = mid_x - center[0]
            dy = mid_y - center[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 0:
                nx, ny = dx / dist, dy / dist
            else:
                nx, ny = 0, 0
            chord_len = math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
            bulge = chord_len * 0.4
            ctrl_x = mid_x + nx * bulge
            ctrl_y = mid_y + ny * bulge
            if i == 0:
                cr.move_to(p1[0], p1[1])
            c1x = p1[0] + 2 / 3 * (ctrl_x - p1[0])
            c1y = p1[1] + 2 / 3 * (ctrl_y - p1[1])
            c2x = p2[0] + 2 / 3 * (ctrl_x - p2[0])
            c2y = p2[1] + 2 / 3 * (ctrl_y - p2[1])
            cr.curve_to(c1x, c1y, c2x, c2y, p2[0], p2[1])
        if closed:
            cr.close_path()

    def _draw_bubble_closed_body(self, cr, segments, outline_width, body_style):
        """Draw a closed bubble body (no tail gap) with the specified style."""
        import math

        if body_style == "jagged":
            points = self._sample_segments(segments, 48)
            center = self._compute_center(points)
            jagged_pts = self._compute_jagged_points(points, center, outline_width)
            cr.new_path()
            cr.move_to(jagged_pts[0][0], jagged_pts[0][1])
            for pt in jagged_pts[1:]:
                cr.line_to(pt[0], pt[1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()
        elif body_style == "cloud":
            points = self._sample_segments(segments, 18)
            center = self._compute_center(points)
            self._build_cloud_path(cr, points, center, closed=True)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()
        else:
            # smooth or dotted — use proper Bézier curves
            cr.new_path()
            for i, seg in enumerate(segments):
                if i == 0:
                    cr.move_to(seg[0][0], seg[0][1])
                cr.curve_to(seg[1][0], seg[1][1], seg[2][0], seg[2][1], seg[3][0], seg[3][1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            if body_style == "dotted":
                cr.set_dash([outline_width * 3, outline_width * 2])
            cr.stroke()
            cr.set_dash([])

    def _draw_bubble_body_with_straight_tail(self, cr, segments, n, scaled_points,
                                              tail_base_t, tail_tip_x, tail_tip_y,
                                              tail_base_width, w, h, outline_width, body_style):
        """Draw bubble body with an integrated straight tail."""
        import math

        # Compute t-offsets for the tail gap
        tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)
        dt = 0.001
        p_dt = self._eval_bubble_curve_at_t(scaled_points, (tail_base_t + dt) % 1.0)
        local_speed = math.sqrt((p_dt[0] - tail_base_pos[0]) ** 2 +
                                (p_dt[1] - tail_base_pos[1]) ** 2) / dt
        t_half_gap = (tail_base_width / 2) / local_speed if local_speed > 0 else 0.02
        t_right = (tail_base_t + t_half_gap) % 1.0
        t_left = (tail_base_t - t_half_gap) % 1.0

        right_point = self._eval_bubble_curve_at_t(scaled_points, t_right)
        left_point = self._eval_bubble_curve_at_t(scaled_points, t_left)

        # Sample body curve from t_right around to t_left (the long way, skipping the gap)
        body_range = 1.0 - 2 * t_half_gap
        num_samples = 300
        body_points = [right_point]
        for i in range(1, num_samples):
            t = (t_right + (i / num_samples) * body_range) % 1.0
            body_points.append(self._eval_bubble_curve_at_t(scaled_points, t))
        body_points.append(left_point)

        tail_tip = (tail_tip_x, tail_tip_y)

        if body_style == "jagged":
            # Jagged: apply zigzag to entire outline including tail edges
            center = self._compute_center(body_points)
            # Resample body to fewer points for visible spikes
            fewer = 40
            sparse_body = [right_point]
            for i in range(1, fewer):
                t = (t_right + (i / fewer) * body_range) % 1.0
                sparse_body.append(self._eval_bubble_curve_at_t(scaled_points, t))
            sparse_body.append(left_point)
            # Add tail tip as extra points
            all_points = sparse_body + [tail_tip]
            jagged_pts = self._compute_jagged_points(all_points, center, outline_width)
            cr.new_path()
            cr.move_to(jagged_pts[0][0], jagged_pts[0][1])
            for pt in jagged_pts[1:]:
                cr.line_to(pt[0], pt[1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()

        elif body_style == "cloud":
            # Cloud bumps on body, straight lines for tail edges
            center = self._compute_center(body_points)
            # Fill the combined shape white first
            cr.new_path()
            cr.move_to(body_points[0][0], body_points[0][1])
            for pt in body_points[1:]:
                cr.line_to(pt[0], pt[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill()
            # Draw cloud outline for body portion
            cloud_n = 16
            cloud_pts = [right_point]
            for i in range(1, cloud_n):
                t = (t_right + (i / cloud_n) * body_range) % 1.0
                cloud_pts.append(self._eval_bubble_curve_at_t(scaled_points, t))
            cloud_pts.append(left_point)
            self._build_cloud_path(cr, cloud_pts, center, closed=False)
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()
            # Draw straight tail edges
            cr.new_path()
            cr.move_to(left_point[0], left_point[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            cr.line_to(right_point[0], right_point[1])
            cr.stroke()

        else:
            # smooth or dotted — use sampled body + tail lines
            cr.new_path()
            cr.move_to(body_points[0][0], body_points[0][1])
            for pt in body_points[1:]:
                cr.line_to(pt[0], pt[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            if body_style == "dotted":
                cr.set_dash([outline_width * 3, outline_width * 2])
            cr.stroke()
            cr.set_dash([])

    def _draw_bubble_body_with_jagged_tail(self, cr, segments, n, scaled_points,
                                              tail_base_t, tail_tip_x, tail_tip_y,
                                              tail_base_width, w, h, outline_width, body_style):
        """Draw bubble body with a jagged tail (1 zigzag in the middle)."""
        import math

        # Compute t-offsets for the tail gap (same as straight tail)
        tail_base_pos = self._eval_bubble_curve_at_t(scaled_points, tail_base_t)
        dt = 0.001
        p_dt = self._eval_bubble_curve_at_t(scaled_points, (tail_base_t + dt) % 1.0)
        local_speed = math.sqrt((p_dt[0] - tail_base_pos[0]) ** 2 +
                                (p_dt[1] - tail_base_pos[1]) ** 2) / dt
        t_half_gap = (tail_base_width / 2) / local_speed if local_speed > 0 else 0.02
        t_right = (tail_base_t + t_half_gap) % 1.0
        t_left = (tail_base_t - t_half_gap) % 1.0

        right_point = self._eval_bubble_curve_at_t(scaled_points, t_right)
        left_point = self._eval_bubble_curve_at_t(scaled_points, t_left)

        # Sample body curve from t_right around to t_left (the long way, skipping the gap)
        body_range = 1.0 - 2 * t_half_gap
        num_samples = 300
        body_points = [right_point]
        for i in range(1, num_samples):
            t = (t_right + (i / num_samples) * body_range) % 1.0
            body_points.append(self._eval_bubble_curve_at_t(scaled_points, t))
        body_points.append(left_point)

        tail_tip = (tail_tip_x, tail_tip_y)

        # Lightning bolt Z-shape on the tail centerline, then offset for edges
        spike_amplitude = 25
        base_cx = (left_point[0] + right_point[0]) / 2
        base_cy = (left_point[1] + right_point[1]) / 2
        tail_dx = tail_tip_x - base_cx
        tail_dy = tail_tip_y - base_cy
        tail_len = math.sqrt(tail_dx * tail_dx + tail_dy * tail_dy)
        if tail_len > 0:
            # Unit vectors along and perpendicular to tail axis
            ax_x = tail_dx / tail_len
            ax_y = tail_dy / tail_len
            perp_x = -ax_y * spike_amplitude
            perp_y = ax_x * spike_amplitude
        else:
            perp_x, perp_y = spike_amplitude, 0

        # Two knees on the centerline: A at 45%, B at 55%, shifted opposite directions
        center_a = (base_cx + 0.45 * tail_dx + perp_x,
                    base_cy + 0.45 * tail_dy + perp_y)
        center_b = (base_cx + 0.55 * tail_dx - perp_x,
                    base_cy + 0.55 * tail_dy - perp_y)

        # Offset each knee for left and right edges using half the base width
        half_w = tail_base_width / 2
        if tail_len > 0:
            edge_ox = -ax_y * half_w
            edge_oy = ax_x * half_w
        else:
            edge_ox, edge_oy = half_w, 0

        # Left edge: left_point → knee_A_left → knee_B_left → tail_tip
        left_mid = [(center_a[0] - edge_ox, center_a[1] - edge_oy),
                    (center_b[0] - edge_ox, center_b[1] - edge_oy)]
        # Right edge: tail_tip → knee_B_right → knee_A_right → right_point
        right_mid = [(center_b[0] + edge_ox, center_b[1] + edge_oy),
                     (center_a[0] + edge_ox, center_a[1] + edge_oy)]

        # Now mirror the straight tail method exactly, just with bolt knees
        if body_style == "jagged":
            center = self._compute_center(body_points)
            fewer = 40
            sparse_body = [right_point]
            for i in range(1, fewer):
                t = (t_right + (i / fewer) * body_range) % 1.0
                sparse_body.append(self._eval_bubble_curve_at_t(scaled_points, t))
            sparse_body.append(left_point)
            # Include bolt knee points and tail tip
            all_points = sparse_body + list(left_mid) + [tail_tip] + list(right_mid)
            jagged_pts = self._compute_jagged_points(all_points, center, outline_width)
            cr.new_path()
            cr.move_to(jagged_pts[0][0], jagged_pts[0][1])
            for pt in jagged_pts[1:]:
                cr.line_to(pt[0], pt[1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()

        elif body_style == "cloud":
            center = self._compute_center(body_points)
            # Fill the combined shape white first
            cr.new_path()
            cr.move_to(body_points[0][0], body_points[0][1])
            for pt in body_points[1:]:
                cr.line_to(pt[0], pt[1])
            for pt in left_mid:
                cr.line_to(pt[0], pt[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            for pt in right_mid:
                cr.line_to(pt[0], pt[1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill()
            # Draw cloud outline for body portion
            cloud_n = 16
            cloud_pts = [right_point]
            for i in range(1, cloud_n):
                t = (t_right + (i / cloud_n) * body_range) % 1.0
                cloud_pts.append(self._eval_bubble_curve_at_t(scaled_points, t))
            cloud_pts.append(left_point)
            self._build_cloud_path(cr, cloud_pts, center, closed=False)
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            cr.stroke()
            # Draw jagged tail edges
            cr.new_path()
            cr.move_to(left_point[0], left_point[1])
            for pt in left_mid:
                cr.line_to(pt[0], pt[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            for pt in right_mid:
                cr.line_to(pt[0], pt[1])
            cr.line_to(right_point[0], right_point[1])
            cr.stroke()

        else:
            # smooth or dotted — same as straight tail but with zigzag midpoints
            cr.new_path()
            cr.move_to(body_points[0][0], body_points[0][1])
            for pt in body_points[1:]:
                cr.line_to(pt[0], pt[1])
            for pt in left_mid:
                cr.line_to(pt[0], pt[1])
            cr.line_to(tail_tip_x, tail_tip_y)
            for pt in right_mid:
                cr.line_to(pt[0], pt[1])
            cr.close_path()
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(outline_width)
            if body_style == "dotted":
                cr.set_dash([outline_width * 3, outline_width * 2])
            cr.stroke()
            cr.set_dash([])

    def _draw_bubble_text(self, cr, element, x, y, w, h, text, text_color):
        """Draw text inside a speech bubble using PangoCairo with word wrapping."""
        text_r, text_g, text_b = self._hex_to_rgb(text_color)
        cr.set_source_rgb(text_r, text_g, text_b)

        text_area_x = element.properties.get("text_area_x", 30) * (w / element.width)
        text_area_y = element.properties.get("text_area_y", 30) * (h / element.height)
        text_area_w = element.properties.get("text_area_width", element.width - 60) * (w / element.width)
        text_area_h = element.properties.get("text_area_height", element.height - 60) * (h / element.height)

        layout = PangoCairo.create_layout(cr)

        font_family = element.properties.get("font", "Arial")
        font_size = element.properties.get("font_size", 14)
        bold = element.properties.get("bold", False)
        italic = element.properties.get("italic", False)

        font_desc = Pango.FontDescription()
        font_desc.set_family(font_family)
        font_desc.set_size(int(font_size * Pango.SCALE))
        if bold:
            font_desc.set_weight(Pango.Weight.BOLD)
        if italic:
            font_desc.set_style(Pango.Style.ITALIC)
        layout.set_font_description(font_desc)
        layout.set_text(text, -1)

        if text_area_w > 0:
            layout.set_width(int(text_area_w * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        if text_area_h > 0:
            layout.set_height(int(text_area_h * Pango.SCALE))

        text_align = element.properties.get("text_align", "center")
        if text_align == "center":
            layout.set_alignment(Pango.Alignment.CENTER)
        elif text_align == "right":
            layout.set_alignment(Pango.Alignment.RIGHT)
        else:
            layout.set_alignment(Pango.Alignment.LEFT)

        # Vertical alignment
        _, layout_height = layout.get_pixel_size()
        vertical_align = element.properties.get("vertical_align", "middle")
        if vertical_align == "middle":
            y_offset = max(0, (text_area_h - layout_height) / 2)
        elif vertical_align == "bottom":
            y_offset = max(0, text_area_h - layout_height)
        else:
            y_offset = 0

        cr.move_to(x + text_area_x, y + text_area_y + y_offset)
        PangoCairo.show_layout(cr, layout)

    @staticmethod
    def _rotation_handle_page_pos(element, scale=1.0):
        """Get the rotation handle position in page coordinates."""
        import math
        cx = element.x + element.width / 2
        cy = element.y + element.height / 2
        # Handle is 30 canvas-pixels above element top-center, rotated with element
        offset = 30 / scale
        rel_y = -element.height / 2 - offset
        a = math.radians(element.rotation)
        hx = cx - rel_y * math.sin(a)
        hy = cy + rel_y * math.cos(a)
        return hx, hy

    def _draw_rotated_element(self, cr, element, x, y, w, h, scale, draw_fn):
        """Draw a TEXT or TEXTAREA element with rotation transform and handles."""
        import math
        angle = element.rotation
        cx = x + w / 2
        cy = y + h / 2

        cr.save()
        if angle != 0:
            cr.translate(cx, cy)
            cr.rotate(math.radians(angle))
            cr.translate(-cx, -cy)

        draw_fn(cr, element, x, y, w, h, scale)

        # Draw selection visuals in rotated space
        if element in self.selected_elements:
            handle_size = 8
            # Resize handles at corners
            selection_color = self.config.get("selection_color", "#0066FF")
            sel_r, sel_g, sel_b = self._hex_to_rgb(selection_color)
            cr.set_source_rgb(sel_r, sel_g, sel_b)
            cr.set_line_width(2)
            cr.set_dash([5, 5])
            cr.rectangle(x, y, w, h)
            cr.stroke()
            cr.set_dash([])

            for hx, hy in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
                cr.rectangle(hx - handle_size / 2, hy - handle_size / 2,
                             handle_size, handle_size)
                cr.fill()

            # Rotation handle: circle above top-center
            if self.rotation_mode:
                rot_handle_y = y - 30
                rot_handle_x = x + w / 2
                # Connecting line
                cr.set_source_rgba(0.2, 0.5, 1.0, 0.6)
                cr.set_line_width(1.5)
                cr.move_to(rot_handle_x, y)
                cr.line_to(rot_handle_x, rot_handle_y)
                cr.stroke()
                # Circle handle
                cr.arc(rot_handle_x, rot_handle_y, 7, 0, 2 * math.pi)
                cr.set_source_rgba(0.2, 0.5, 1.0, 0.8)
                cr.fill_preserve()
                cr.set_source_rgb(1, 1, 1)
                cr.set_line_width(1.5)
                cr.stroke()
                # Rotation arrow icon inside circle
                cr.set_source_rgb(1, 1, 1)
                cr.set_line_width(1.5)
                cr.arc(rot_handle_x, rot_handle_y, 4, -math.pi * 0.8, math.pi * 0.4)
                cr.stroke()

        cr.restore()

    def _draw_text_element(self, cr, element, x, y, w, h, scale):
        """Draw a title/large text element with fill, outline, and style."""
        props = element.properties
        text = props.get("text", "TITLE")
        if not text:
            text = " "

        font_family = props.get("font", "Impact")
        font_size = props.get("font_size", 72)
        bold = props.get("bold", False)
        italic = props.get("italic", False)
        text_align = props.get("text_align", "center")
        fill_color = props.get("fill_color", "#FFFFFF")
        outline_color = props.get("outline_color", "#000000")
        outline_width = props.get("outline_width", 2)
        text_style = props.get("text_style", "normal")

        # Create Pango layout (scale font size with zoom)
        scaled_font_size = font_size * scale
        layout = PangoCairo.create_layout(cr)
        font_desc = Pango.FontDescription()
        font_desc.set_family(font_family)
        font_desc.set_size(int(scaled_font_size * Pango.SCALE))
        if bold:
            font_desc.set_weight(Pango.Weight.BOLD)
        if italic:
            font_desc.set_style(Pango.Style.ITALIC)
        layout.set_font_description(font_desc)
        layout.set_text(text, -1)
        layout.set_line_spacing(props.get("line_spacing", 1.0))

        if w > 0:
            layout.set_width(int(w * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        if text_align == "center":
            layout.set_alignment(Pango.Alignment.CENTER)
        elif text_align == "right":
            layout.set_alignment(Pango.Alignment.RIGHT)
        else:
            layout.set_alignment(Pango.Alignment.LEFT)

        # Vertical center
        _, layout_height = layout.get_pixel_size()
        y_offset = max(0, (h - layout_height) / 2)

        tx = x
        ty = y + y_offset

        fr, fg, fb = self._hex_to_rgb(fill_color)
        or_, og, ob = self._hex_to_rgb(outline_color)

        if text_style == "shadow":
            # Draw shadow offset
            shadow_offset = max(2, scaled_font_size * 0.04)
            cr.save()
            cr.move_to(tx + shadow_offset, ty + shadow_offset)
            PangoCairo.layout_path(cr, layout)
            cr.set_source_rgba(0, 0, 0, 0.4)
            cr.fill()
            cr.restore()
            # Draw outline
            if outline_width > 0:
                cr.save()
                cr.move_to(tx, ty)
                PangoCairo.layout_path(cr, layout)
                cr.set_source_rgb(or_, og, ob)
                cr.set_line_width(outline_width)
                cr.set_line_join(1)  # ROUND
                cr.stroke()
                cr.restore()
            # Draw fill
            cr.move_to(tx, ty)
            cr.set_source_rgb(fr, fg, fb)
            PangoCairo.show_layout(cr, layout)

        elif text_style == "outline only":
            # Outline only, no fill
            cr.save()
            cr.move_to(tx, ty)
            PangoCairo.layout_path(cr, layout)
            cr.set_source_rgb(or_, og, ob)
            cr.set_line_width(max(outline_width, 1))
            cr.set_line_join(1)  # ROUND
            cr.stroke()
            cr.restore()

        elif text_style == "raised":
            # Multiple shadow layers for a raised/3D effect
            depth = max(3, int(scaled_font_size * 0.06))
            for i in range(depth, 0, -1):
                cr.save()
                cr.move_to(tx + i, ty + i)
                PangoCairo.layout_path(cr, layout)
                shade = 0.15 + 0.1 * (i / depth)
                cr.set_source_rgb(shade, shade, shade)
                cr.fill()
                cr.restore()
            # Draw outline
            if outline_width > 0:
                cr.save()
                cr.move_to(tx, ty)
                PangoCairo.layout_path(cr, layout)
                cr.set_source_rgb(or_, og, ob)
                cr.set_line_width(outline_width)
                cr.set_line_join(1)  # ROUND
                cr.stroke()
                cr.restore()
            # Draw fill
            cr.move_to(tx, ty)
            cr.set_source_rgb(fr, fg, fb)
            PangoCairo.show_layout(cr, layout)

        else:
            # Normal: outline then fill
            if outline_width > 0:
                cr.save()
                cr.move_to(tx, ty)
                PangoCairo.layout_path(cr, layout)
                cr.set_source_rgb(or_, og, ob)
                cr.set_line_width(outline_width)
                cr.set_line_join(1)  # ROUND
                cr.stroke()
                cr.restore()
            cr.move_to(tx, ty)
            cr.set_source_rgb(fr, fg, fb)
            PangoCairo.show_layout(cr, layout)

    def _draw_textarea_element(self, cr, element, x, y, w, h, scale):
        """Draw a text area element with background, border, shadow, and text."""
        import math
        props = element.properties

        bg_color = props.get("background_color", "#FFFFFF")
        border_color = props.get("border_color", "#000000")
        border_width = props.get("border_width", 1)
        border_radius = props.get("border_radius", 0) * scale
        text_color = props.get("text_color", "#000000")
        text = props.get("text", "")
        font_family = props.get("font", "Arial")
        font_size = props.get("font_size", 16)
        bold = props.get("bold", False)
        italic = props.get("italic", False)
        text_align = props.get("text_align", "left")
        padding = props.get("padding", 10) * scale
        shadow_enabled = props.get("shadow_enabled", False)

        def rounded_rect(cr, rx, ry, rw, rh, r):
            """Draw a rounded rectangle path."""
            r = min(r, rw / 2, rh / 2)
            if r <= 0:
                cr.rectangle(rx, ry, rw, rh)
                return
            cr.new_path()
            cr.arc(rx + rw - r, ry + r, r, -math.pi / 2, 0)
            cr.arc(rx + rw - r, ry + rh - r, r, 0, math.pi / 2)
            cr.arc(rx + r, ry + rh - r, r, math.pi / 2, math.pi)
            cr.arc(rx + r, ry + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()

        # Draw drop shadow
        if shadow_enabled:
            sx = props.get("shadow_offset_x", 4) * scale
            sy = props.get("shadow_offset_y", 4) * scale
            shadow_color = props.get("shadow_color", "#00000040")
            if len(shadow_color) == 9:
                sr, sg, sb = self._hex_to_rgb(shadow_color[:7])
                sa = int(shadow_color[7:9], 16) / 255.0
            else:
                sr, sg, sb = self._hex_to_rgb(shadow_color)
                sa = 0.25
            # Draw multiple offset rectangles for blur approximation
            blur = int(props.get("shadow_blur", 0))
            if blur > 0:
                steps = min(blur, 8)
                for i in range(steps, 0, -1):
                    frac = i / steps
                    expand = frac * blur * scale
                    cr.set_source_rgba(sr, sg, sb, sa * (1 - frac) * 0.5)
                    rounded_rect(cr, x + sx - expand, y + sy - expand,
                                 w + expand * 2, h + expand * 2, border_radius + expand)
                    cr.fill()
            cr.set_source_rgba(sr, sg, sb, sa)
            rounded_rect(cr, x + sx, y + sy, w, h, border_radius)
            cr.fill()

        # Draw background
        bg_r, bg_g, bg_b = self._hex_to_rgb(bg_color)
        cr.set_source_rgb(bg_r, bg_g, bg_b)
        rounded_rect(cr, x, y, w, h, border_radius)
        cr.fill()

        # Draw border
        if border_width > 0:
            bc_r, bc_g, bc_b = self._hex_to_rgb(border_color)
            cr.set_source_rgb(bc_r, bc_g, bc_b)
            cr.set_line_width(border_width)
            rounded_rect(cr, x, y, w, h, border_radius)
            cr.stroke()

        # Draw text with Pango
        if text:
            scaled_font_size = font_size * scale
            layout = PangoCairo.create_layout(cr)
            font_desc = Pango.FontDescription()
            font_desc.set_family(font_family)
            font_desc.set_size(int(scaled_font_size * Pango.SCALE))
            if bold:
                font_desc.set_weight(Pango.Weight.BOLD)
            if italic:
                font_desc.set_style(Pango.Style.ITALIC)
            layout.set_font_description(font_desc)
            layout.set_text(text, -1)
            layout.set_line_spacing(props.get("line_spacing", 1.0))

            text_w = w - padding * 2
            if text_w > 0:
                layout.set_width(int(text_w * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            text_h = h - padding * 2
            if text_h > 0:
                layout.set_height(int(text_h * Pango.SCALE))

            if text_align == "center":
                layout.set_alignment(Pango.Alignment.CENTER)
            elif text_align == "right":
                layout.set_alignment(Pango.Alignment.RIGHT)
            else:
                layout.set_alignment(Pango.Alignment.LEFT)

            tc_r, tc_g, tc_b = self._hex_to_rgb(text_color)
            cr.set_source_rgb(tc_r, tc_g, tc_b)
            cr.move_to(x + padding, y + padding)
            PangoCairo.show_layout(cr, layout)

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

    def _split_bezier_at_t(self, p0, p1, p2, p3, t):
        """Split cubic Bézier at parameter t using De Casteljau's algorithm.
        Returns (left_segment, right_segment) each as (p0, p1, p2, p3)."""
        m01 = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
        m12 = (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
        m23 = (p2[0] + t * (p3[0] - p2[0]), p2[1] + t * (p3[1] - p2[1]))
        m012 = (m01[0] + t * (m12[0] - m01[0]), m01[1] + t * (m12[1] - m01[1]))
        m123 = (m12[0] + t * (m23[0] - m12[0]), m12[1] + t * (m23[1] - m12[1]))
        split = (m012[0] + t * (m123[0] - m012[0]), m012[1] + t * (m123[1] - m012[1]))

        left = (p0, m01, m012, split)
        right = (split, m123, m23, p3)
        return left, right
    
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
    
    def _scale_speech_bubble_on_resize(self, element, scale_x, scale_y):
        """Scale speech bubble control points, text area, and tail proportionally."""
        if element.type != ElementType.SPEECH_BUBBLE:
            return

        # Scale control points
        control_points = element.properties.get("control_points")
        if control_points:
            element.properties["control_points"] = [
                (px * scale_x, py * scale_y) for px, py in control_points
            ]

        # Scale text area position and size
        for key in ("text_area_x", "text_area_width"):
            if key in element.properties:
                element.properties[key] = element.properties[key] * scale_x
        for key in ("text_area_y", "text_area_height"):
            if key in element.properties:
                element.properties[key] = element.properties[key] * scale_y

        # Scale tail tip position
        if "tail_tip_x" in element.properties:
            element.properties["tail_tip_x"] = element.properties["tail_tip_x"] * scale_x
        if "tail_tip_y" in element.properties:
            element.properties["tail_tip_y"] = element.properties["tail_tip_y"] * scale_y

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
        """Export project as CBZ."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Export as CBZ")
        dialog.set_initial_name(f"{self.project.name}.cbz")

        cbz_filter = Gtk.FileFilter()
        cbz_filter.set_name("CBZ Archive (*.cbz)")
        cbz_filter.add_pattern("*.cbz")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(cbz_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(cbz_filter)

        dialog.save(self, None, self._on_export_file_chosen)

    def _on_export_file_chosen(self, dialog, result):
        """Handle export file selection."""
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # User cancelled

        export_path = gfile.get_path()
        if not export_path.lower().endswith('.cbz'):
            export_path += '.cbz'

        self._run_cbz_export(export_path)

    def _run_cbz_export(self, export_path):
        """Run the CBZ export with a progress dialog."""
        import threading

        total = len(self.project.pages)
        if total == 0:
            return

        # Create progress dialog
        self._export_dialog = Gtk.Window(title="Exporting CBZ...")
        self._export_dialog.set_transient_for(self)
        self._export_dialog.set_modal(True)
        self._export_dialog.set_resizable(False)
        self._export_dialog.set_default_size(350, -1)
        self._export_dialog.set_deletable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        self._export_label = Gtk.Label(label=f"Rendering page 1 of {total}...")
        box.append(self._export_label)

        self._export_progress = Gtk.ProgressBar()
        self._export_progress.set_fraction(0)
        box.append(self._export_progress)

        self._export_dialog.set_child(box)
        self._export_dialog.present()

        # Save and clear selection state so it doesn't render into export
        saved_selection = self.selected_elements[:]
        saved_mode = self.selection_mode
        self.selected_elements = []
        self.selection_mode = 'panel'

        def export_thread():
            import zipfile
            import cairo
            import io
            from PIL import Image as PILImage

            try:
                with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_STORED) as zf:
                    for idx, page in enumerate(self.project.pages):
                        # Render page to cairo surface
                        width = page.width
                        height = page.height
                        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                        cr = cairo.Context(surface)

                        # White background
                        cr.set_source_rgb(1, 1, 1)
                        cr.paint()

                        # Draw all elements at scale=1, offset=0
                        for element in page.elements:
                            self._draw_element(cr, element, 0, 0, 1.0)

                        surface.flush()

                        # Convert cairo ARGB32 surface to PNG bytes via PIL (strips metadata)
                        buf = surface.get_data()
                        pil_img = PILImage.frombuffer(
                            "RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1
                        )
                        # Convert to RGB (no alpha) for comic viewers
                        pil_img = pil_img.convert("RGB")

                        png_buf = io.BytesIO()
                        pil_img.save(png_buf, format="PNG", pnginfo=None)
                        png_bytes = png_buf.getvalue()

                        page_name = f"page-{idx + 1}.png"
                        zf.writestr(page_name, png_bytes)

                        # Update progress on main thread
                        fraction = (idx + 1) / total
                        GLib.idle_add(self._update_export_progress, idx + 1, total, fraction)

                GLib.idle_add(self._finish_export, export_path, saved_selection, saved_mode, None)
            except Exception as e:
                GLib.idle_add(self._finish_export, export_path, saved_selection, saved_mode, str(e))

        thread = threading.Thread(target=export_thread, daemon=True)
        thread.start()

    def _update_export_progress(self, current, total, fraction):
        """Update export progress bar (called on main thread)."""
        self._export_progress.set_fraction(fraction)
        self._export_label.set_text(f"Rendering page {current} of {total}...")
        return False

    def _finish_export(self, export_path, saved_selection, saved_mode, error):
        """Finish export (called on main thread)."""
        # Restore selection state
        self.selected_elements = saved_selection
        self.selection_mode = saved_mode
        self.canvas.queue_draw()

        self._export_dialog.close()
        self._export_dialog = None

        # Show result dialog
        alert = Gtk.AlertDialog()
        if error:
            alert.set_message("Export Failed")
            alert.set_detail(f"Error: {error}")
        else:
            alert.set_message("Export Complete")
            alert.set_detail(f"Saved to:\n{export_path}")
        alert.set_buttons(["OK"])
        alert.choose(self, None, None, None)
        return False
    
    def _on_settings(self, action, param):
        """Open settings dialog."""
        pass
    
    def _on_quit(self, action, param):
        """Quit application."""
        self.get_application().quit()
    
    def _snapshot_element(self, element):
        """Capture element state for undo."""
        return {
            "x": element.x,
            "y": element.y,
            "width": element.width,
            "height": element.height,
            "rotation": element.rotation,
            "properties": copy.deepcopy(element.properties),
        }

    def _on_undo(self, action, param):
        """Undo last action."""
        self.undo_manager.undo()
        self.selected_elements = []
        self._update_properties_panel()
        self._update_layer_buttons()
        self.canvas.queue_draw()

    def _on_redo(self, action, param):
        """Redo last action."""
        self.undo_manager.redo()
        self.selected_elements = []
        self._update_properties_panel()
        self._update_layer_buttons()
        self.canvas.queue_draw()
    
    def _on_copy(self, action, param):
        """Copy selected elements to internal clipboard."""
        if not self.selected_elements:
            return
        self._clipboard_elements = [
            el.to_dict() for el in self.selected_elements
        ]

    def _on_paste(self, action, param):
        """Paste elements from internal clipboard onto the current page."""
        if not self._clipboard_elements or not self.current_page:
            return
        import uuid as _uuid
        paste_offset = 20
        new_selection = []
        for data in self._clipboard_elements:
            el = Element.from_dict(data)
            el.id = str(_uuid.uuid4())
            el.x += paste_offset
            el.y += paste_offset
            self.current_page.add_element(el)
            self.undo_manager.push_command(
                AddElementCommand(self.current_page, el))
            new_selection.append(el)
        self.selected_elements = new_selection
        self._update_properties_panel()
        self._update_layer_buttons()
        self.canvas.queue_draw()
    
    def _on_zoom_in(self, action, param):
        """Zoom in."""
        max_zoom = self.config.get("max_zoom", 800)
        self.zoom_level = min(self.zoom_level * 1.08, max_zoom)
        self.zoom_label.set_text(f"{int(self.zoom_level)}%")
        self._update_canvas_size()
        self.canvas.queue_draw()

    def _on_zoom_out(self, action, param):
        """Zoom out."""
        min_zoom = self.config.get("min_zoom", 10)
        self.zoom_level = max(self.zoom_level / 1.08, min_zoom)
        self.zoom_label.set_text(f"{int(self.zoom_level)}%")
        self._update_canvas_size()
        self.canvas.queue_draw()
    
    def _on_full_page(self, action, param):
        """Zoom to fit full page in the visible viewport."""
        if self.current_page:
            padding = 100
            vp_width = self.scrolled.get_width()
            vp_height = self.scrolled.get_height()
            if vp_width < 1 or vp_height < 1:
                return
            zoom_w = ((vp_width - padding * 2) / self.current_page.width) * 100
            zoom_h = ((vp_height - padding * 2) / self.current_page.height) * 100
            self.zoom_level = min(zoom_w, zoom_h)
            self.pan_offset_x = 0
            self.pan_offset_y = 0
            self.zoom_label.set_text(f"{int(self.zoom_level)}%")
            self._update_canvas_size()
            self.canvas.queue_draw()

    def _on_page_width(self, action, param):
        """Zoom to fit page width in the visible viewport."""
        if self.current_page:
            padding = 100
            vp_width = self.scrolled.get_width()
            if vp_width < 1:
                return
            self.zoom_level = ((vp_width - padding * 2) / self.current_page.width) * 100
            self.pan_offset_x = 0
            self.pan_offset_y = 0
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
            # Spline-based bubbles (round or thought) support edit mode
            if element.properties.get("control_points") is not None:
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

        # Don't intercept keys when text view has focus
        if self.prop_text_view.has_focus():
            return False

        # Check if Ctrl is pressed
        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK
        
        if ctrl_pressed:
            # Ctrl+S for save
            if keyval == Gdk.KEY_s:
                self._on_save(None, None)
                return True
            # Ctrl+C for copy
            elif keyval == Gdk.KEY_c:
                self._on_copy(None, None)
                return True
            # Ctrl+V for paste
            elif keyval == Gdk.KEY_v:
                self._on_paste(None, None)
                return True
            # Ctrl+Z for undo, Ctrl+Shift+Z for redo
            elif keyval == Gdk.KEY_z:
                if state & Gdk.ModifierType.SHIFT_MASK:
                    self._on_redo(None, None)
                else:
                    self._on_undo(None, None)
                return True
            elif keyval == Gdk.KEY_y:
                self._on_redo(None, None)
                return True
            # Ctrl + = or Ctrl + Plus for zoom in
            elif keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
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
                    idx = self.current_page.elements.index(element)
                    self.current_page.elements.remove(element)
                    self.undo_manager.push_command(
                        RemoveElementCommand(self.current_page, element, idx))
                self.selected_elements = []
                self.edit_mode_element = None  # Exit edit mode if deleting element
                self._update_layer_buttons()
                self._update_properties_panel()
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
        # Check if it's an image from the library
        if element_type.startswith('image_lib:'):
            image_filename = element_type[len('image_lib:'):]
            return self._handle_image_lib_drop(image_filename, x, y)

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
            self.undo_manager.push_command(
                AddElementCommand(self.current_page, element))
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
            if ((element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and
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
            self.undo_manager.push_command(
                AddElementCommand(self.current_page, panel))

        self.canvas.queue_draw()
        return True
    
    def _create_element_from_type(self, element_type, x, y):
        """Create an element from a type string."""
        if element_type == "custom_panel":
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
        
        elif element_type == "circle_panel":
            width = self.current_page.width * 0.2
            height = self.current_page.width * 0.2  # Square bounding box for circle
            return Element(
                ElementType.CIRCLE_PANEL,
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

        elif element_type == "text":
            return Element(
                ElementType.TEXT,
                x, y, 400, 100,
                text="TITLE",
                font="Bangers",
                font_size=72,
                line_spacing=1.0,
                bold=False,
                italic=False,
                text_align="center",
                fill_color="#FFFFFF",
                outline_color="#000000",
                outline_width=2,
                text_style="normal",
            )

        elif element_type == "textarea":
            return Element(
                ElementType.TEXTAREA,
                x, y, 300, 150,
                text="Enter text here",
                font="Arial",
                font_size=16,
                line_spacing=1.0,
                bold=False,
                italic=False,
                text_align="left",
                text_color="#000000",
                background_color="#FFFFFF",
                border_color="#000000",
                border_width=1,
                border_radius=0,
                shadow_enabled=False,
                shadow_color="#00000040",
                shadow_offset_x=4,
                shadow_offset_y=4,
                shadow_blur=0,
                padding=10,
            )
        
        elif element_type.startswith("speech_bubble"):
            # Unified speech bubble creation
            import math
            width = 200
            height = 150

            cx = width / 2
            cy = height / 2
            rx = width / 2
            ry = height / 2

            control_points = []
            for i in range(8):
                angle = (i * 2 * math.pi) / 8
                px = cx + rx * math.cos(angle)
                py = cy + ry * math.sin(angle)
                control_points.append((px, py))

            return Element(
                ElementType.SPEECH_BUBBLE,
                x, y, width, height,
                body_style="smooth",
                tail_style="straight",
                control_points=control_points,
                tail_base_t=0.75,
                tail_base_width=30,
                tail_tip_x=cx - 30,
                tail_tip_y=height + 50,
                tail_circles=3,
                text="",
                font="Arial",
                font_size=14,
                text_color="#000000",
                text_align="center",
                vertical_align="middle",
                bold=False,
                italic=False,
                outline_width=1.0,
                text_area_x=30,
                text_area_y=30,
                text_area_width=width - 60,
                text_area_height=height - 60
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
            # Check panel bounds (un-rotate point for rotated elements)
            hit_px, hit_py = page_x, page_y
            if element.rotation != 0 and element.type in (ElementType.TEXT, ElementType.TEXTAREA):
                import math
                cx = element.x + element.width / 2
                cy = element.y + element.height / 2
                a = math.radians(-element.rotation)
                dx_r, dy_r = page_x - cx, page_y - cy
                hit_px = cx + dx_r * math.cos(a) - dy_r * math.sin(a)
                hit_py = cy + dx_r * math.sin(a) + dy_r * math.cos(a)
            in_panel = (element.x <= hit_px <= element.x + element.width and
                       element.y <= hit_py <= element.y + element.height)

            # If element is selected in image mode, also check image bounds (which may extend outside panel)
            # Include margin for resize handles
            in_image = False
            if (element in self.selected_elements and
                self.selection_mode == 'image' and
                (element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and
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

            # Check if clicking on a speech bubble tail handle (which may be outside element bounds)
            on_tail_handle = False
            if element.type == ElementType.SPEECH_BUBBLE and element in self.selected_elements:
                tail_tip_x = element.properties.get("tail_tip_x", element.width / 2)
                tail_tip_y = element.properties.get("tail_tip_y", element.height + 50)
                tail_px = element.x + tail_tip_x
                tail_py = element.y + tail_tip_y
                if (abs(page_x - tail_px) < handle_margin and
                    abs(page_y - tail_py) < handle_margin):
                    on_tail_handle = True

                # Also check tail base handle for spline bubbles
                control_points = element.properties.get("control_points")
                if control_points:
                    scaled_pts = [(element.x + px, element.y + py) for px, py in control_points]
                    tail_base_t = element.properties.get("tail_base_t", 0.75)
                    base_pos = self._eval_bubble_curve_at_t(scaled_pts, tail_base_t)
                    if (abs(page_x - base_pos[0]) < handle_margin and
                        abs(page_y - base_pos[1]) < handle_margin):
                        on_tail_handle = True

            if in_panel or in_image or on_tail_handle:
                clicked_element = element
                break
        
        # Update selection based on single or double click
        if clicked_element:
            if n_press == 1:
                # Single click
                if clicked_element in self.selected_elements:
                    # Clicking on already selected element
                    if clicked_element.type in (ElementType.TEXT, ElementType.TEXTAREA):
                        # Toggle rotation mode for text elements
                        self.rotation_mode = not self.rotation_mode
                    # else: keep current mode (sticky image selection)
                else:
                    self.rotation_mode = False
                    # Clicking on different element - select it in panel mode
                    self.selected_elements = [clicked_element]
                    self.selection_mode = 'panel'
            elif n_press == 2:
                # Double click - toggle between panel and image mode, or edit bubble text
                if clicked_element.type == ElementType.SPEECH_BUBBLE:
                    # Double-click on speech bubble: select and focus text editor
                    self.selected_elements = [clicked_element]
                    self.selection_mode = 'panel'
                    self._update_layer_buttons()
                    self._update_properties_panel()
                    self.prop_text_view.grab_focus()
                    self.canvas.queue_draw()
                    return
                elif clicked_element.type == ElementType.TEXTAREA:
                    # Double-click on textarea: select and focus text editor
                    self.selected_elements = [clicked_element]
                    self.selection_mode = 'panel'
                    self._update_layer_buttons()
                    self._update_properties_panel()
                    self.ta_prop_text.grab_focus()
                    self.canvas.queue_draw()
                    return
                elif clicked_element.type == ElementType.TEXT:
                    # Double-click on title text: select and focus text editor
                    self.selected_elements = [clicked_element]
                    self.selection_mode = 'panel'
                    self._update_layer_buttons()
                    self._update_properties_panel()
                    self.text_prop_text.grab_focus()
                    self.canvas.queue_draw()
                    return
                elif clicked_element in self.selected_elements:
                    if self.selection_mode == 'panel':
                        # Panel mode -> Image mode (if panel has image)
                        if ((clicked_element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and
                            clicked_element.properties.get("image")):
                            self.selection_mode = 'image'
                    else:
                        # Image mode -> Panel mode
                        self.selection_mode = 'panel'
                else:
                    # Double clicking on new element - select and go to image mode if available
                    self.selected_elements = [clicked_element]
                    if (clicked_element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL) and
                        clicked_element.properties.get("image")):
                        self.selection_mode = 'image'
                    else:
                        self.selection_mode = 'panel'
        else:
            # Clicked on empty space
            self.selected_elements = []
            self.selection_mode = 'panel'
            self.rotation_mode = False
        
        self._update_layer_buttons()
        self._update_properties_panel()
        self.canvas.queue_draw()

    def _on_canvas_right_click(self, gesture, n_press, x, y):
        """Handle right-click on canvas for context menu."""
        if not self.current_page or not self.selected_elements:
            return
        
        element = self.selected_elements[0]
        
        # Only show context menu for custom panels and spline-based speech bubbles
        is_custom_panel = element.type == ElementType.CUSTOM_PANEL
        is_spline_bubble = (element.type == ElementType.SPEECH_BUBBLE and
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

        # Check if clicking on a gridline
        if self.gridlines_visible:
            gl = self._hit_test_gridline(start_x, start_y)
            if gl is not None:
                self.dragging_gridline = gl
                self.canvas.set_cursor(
                    Gdk.Cursor.new_from_name("row-resize" if gl[0] == "h" else "col-resize", None)
                )
                return

        # If no element is selected, pan the canvas
        if not self.selected_elements:
            self.panning = True
            self.pan_start_offset_x = self.pan_offset_x
            self.pan_start_offset_y = self.pan_offset_y
            self.canvas.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))
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
        
        # Check if clicking on rotation handle for TEXT / TEXTAREA
        if (self.rotation_mode and
            element.type in (ElementType.TEXT, ElementType.TEXTAREA)):
            import math
            rot_hx, rot_hy = self._rotation_handle_page_pos(element, scale)
            handle_radius = 10 / scale
            if ((page_x - rot_hx) ** 2 + (page_y - rot_hy) ** 2) <= handle_radius ** 2:
                cx = element.x + element.width / 2
                cy = element.y + element.height / 2
                self.rotating_element = element
                self.rotation_start_angle = element.rotation
                self.rotation_drag_start_angle = math.degrees(
                    math.atan2(page_y - cy, page_x - cx))
                self.canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
                return

        # Check if clicking on custom panel vertex handle in edit mode (not in image mode)
        if (element.type == ElementType.CUSTOM_PANEL and
            element == self.edit_mode_element and
            self.selection_mode != 'image'):
            vertices = element.properties.get("vertices", [])
            handle_size = 16 / scale
            
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
        if self.selection_mode == 'image' and (element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and element.properties.get("image"):
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

            # Un-rotate click point for rotated TEXT/TEXTAREA elements
            local_px, local_py = page_x, page_y
            if element.rotation != 0 and element.type in (ElementType.TEXT, ElementType.TEXTAREA):
                import math
                cx = element.x + element.width / 2
                cy = element.y + element.height / 2
                a = math.radians(-element.rotation)
                dx_r, dy_r = page_x - cx, page_y - cy
                local_px = cx + dx_r * math.cos(a) - dy_r * math.sin(a)
                local_py = cy + dx_r * math.sin(a) + dy_r * math.cos(a)

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
                    if (hx - handle_size <= local_px <= hx + handle_size and
                        hy - handle_size <= local_py <= hy + handle_size):
                        self.resizing_element = element
                        self.resizing_image = False
                        self.resize_handle = handle_name
                        self.drag_start_x = page_x
                        self.drag_start_y = page_y
                        self.element_start_x = element.x
                        self.element_start_y = element.y
                        self.element_start_width = element.width
                        self.element_start_height = element.height
                        self._undo_pre_state = self._snapshot_element(element)
                        return

            # If not on a handle and not in edit mode, start dragging the element
            if (not in_edit_mode and
                element.x <= local_px <= element.x + element.width and
                element.y <= local_py <= element.y + element.height):
                self.dragging_element = element
                self.dragging_image = False
                self.drag_start_x = page_x
                self.drag_start_y = page_y
                self.element_start_x = element.x
                self.element_start_y = element.y
                self._undo_pre_state = self._snapshot_element(element)
                return

        # Click didn't hit any element or handle — pan the canvas
        self.panning = True
        self.pan_start_offset_x = self.pan_offset_x
        self.pan_start_offset_y = self.pan_offset_y
        self.canvas.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Handle drag update for moving/resizing elements or panning."""
        # Handle gridline dragging
        if self.dragging_gridline is not None:
            scale = self.zoom_level / 100.0
            orientation, idx = self.dragging_gridline
            # Get current position from gesture
            ok, start_x, start_y = gesture.get_start_point()
            if ok:
                canvas_x = start_x + offset_x
                canvas_y = start_y + offset_y
                padding = 100
                if orientation == "h":
                    page_y = (canvas_y - padding - self.pan_offset_y) / scale
                    page_y = max(0, min(page_y, self.current_page.height))
                    self.project.gridlines_h[idx] = page_y
                else:
                    page_x = (canvas_x - padding - self.pan_offset_x) / scale
                    page_x = max(0, min(page_x, self.current_page.width))
                    self.project.gridlines_v[idx] = page_x
            self.canvas.queue_draw()
            return

        # Handle panning (Shift+drag)
        if self.panning:
            # Update pan offsets - add current drag to accumulated offset
            self.pan_offset_x = self.pan_start_offset_x + offset_x
            self.pan_offset_y = self.pan_start_offset_y + offset_y
            # Trigger redraw
            self.canvas.queue_draw()
            return
        
        # Handle rotation drag
        if self.rotating_element:
            import math
            scale = self.zoom_level / 100.0
            padding = 100
            ok, start_x, start_y = gesture.get_start_point()
            cur_x = start_x + offset_x
            cur_y = start_y + offset_y
            x_offset = padding + self.pan_offset_x
            y_offset_p = padding + self.pan_offset_y
            page_x = (cur_x - x_offset) / scale
            page_y = (cur_y - y_offset_p) / scale
            elem = self.rotating_element
            cx = elem.x + elem.width / 2
            cy = elem.y + elem.height / 2
            current_angle = math.degrees(math.atan2(page_y - cy, page_x - cx))
            delta = current_angle - self.rotation_drag_start_angle
            elem.rotation = self.rotation_start_angle + delta
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

                # Update image offset
                element.properties["image_offset_x"] = new_offset_x
                element.properties["image_offset_y"] = new_offset_y

                # Snap image edges to panel edges and gridlines
                self._snap_image_in_panel(element)
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

                # Snap to gridlines
                self._snap_to_gridlines(self.dragging_element)
            
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

                    # Snap image edges during resize
                    self._snap_image_resize_in_panel(element, aspect_ratio)

                self.canvas.queue_draw()
            else:
                # Resizing the panel itself
                # For custom panels, we need to scale vertices
                # For speech bubbles, we need to scale control points, text area, and tail
                is_custom_panel = element.type == ElementType.CUSTOM_PANEL
                is_speech_bubble = element.type == ElementType.SPEECH_BUBBLE

                if self.resize_handle == 'top-left':
                    new_x = self.element_start_x + dx
                    new_y = self.element_start_y + dy
                    new_width = self.element_start_width - dx
                    new_height = self.element_start_height - dy
                    new_x, new_y, new_width, new_height = self._snap_resize_candidates(
                        new_x, new_y, new_width, new_height, self.resize_handle)

                    if new_width > 20 and new_height > 20:
                        scale_x = new_width / element.width
                        scale_y = new_height / element.height
                        if is_custom_panel:
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        if is_speech_bubble:
                            self._scale_speech_bubble_on_resize(element, scale_x, scale_y)

                        element.x = new_x
                        element.y = new_y
                        element.width = new_width
                        element.height = new_height

                elif self.resize_handle == 'top-right':
                    new_x = element.x
                    new_y = self.element_start_y + dy
                    new_width = self.element_start_width + dx
                    new_height = self.element_start_height - dy
                    new_x, new_y, new_width, new_height = self._snap_resize_candidates(
                        new_x, new_y, new_width, new_height, self.resize_handle)

                    if new_width > 20 and new_height > 20:
                        scale_x = new_width / element.width
                        scale_y = new_height / element.height
                        if is_custom_panel:
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        if is_speech_bubble:
                            self._scale_speech_bubble_on_resize(element, scale_x, scale_y)

                        element.y = new_y
                        element.width = new_width
                        element.height = new_height

                elif self.resize_handle == 'bottom-left':
                    new_x = self.element_start_x + dx
                    new_y = element.y
                    new_width = self.element_start_width - dx
                    new_height = self.element_start_height + dy
                    new_x, new_y, new_width, new_height = self._snap_resize_candidates(
                        new_x, new_y, new_width, new_height, self.resize_handle)

                    if new_width > 20 and new_height > 20:
                        scale_x = new_width / element.width
                        scale_y = new_height / element.height
                        if is_custom_panel:
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        if is_speech_bubble:
                            self._scale_speech_bubble_on_resize(element, scale_x, scale_y)

                        element.x = new_x
                        element.width = new_width
                        element.height = new_height

                elif self.resize_handle == 'bottom-right':
                    new_x = element.x
                    new_y = element.y
                    new_width = self.element_start_width + dx
                    new_height = self.element_start_height + dy
                    new_x, new_y, new_width, new_height = self._snap_resize_candidates(
                        new_x, new_y, new_width, new_height, self.resize_handle)

                    if new_width > 20 and new_height > 20:
                        scale_x = new_width / element.width
                        scale_y = new_height / element.height
                        if is_custom_panel:
                            vertices = element.properties.get("vertices", [])
                            scaled_vertices = []
                            for vertex in vertices:
                                vx, vy = vertex if isinstance(vertex, (list, tuple)) else (vertex.get("x", 0), vertex.get("y", 0))
                                scaled_vertices.append((vx * scale_x, vy * scale_y))
                            element.properties["vertices"] = scaled_vertices
                        if is_speech_bubble:
                            self._scale_speech_bubble_on_resize(element, scale_x, scale_y)

                        element.width = new_width
                        element.height = new_height

                self.canvas.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle drag end."""
        # Handle gridline drag end — remove if dragged off page
        if self.dragging_gridline is not None:
            orientation, idx = self.dragging_gridline
            if orientation == "h":
                val = self.project.gridlines_h[idx]
                if val <= 0 or val >= self.current_page.height:
                    self.project.gridlines_h.pop(idx)
            else:
                val = self.project.gridlines_v[idx]
                if val <= 0 or val >= self.current_page.width:
                    self.project.gridlines_v.pop(idx)
            self.dragging_gridline = None
            self.canvas.set_cursor(None)
            self.canvas.queue_draw()
            return

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
        
        # Push undo command for move/resize if we have a pre-state
        if self._undo_pre_state is not None:
            moved_element = self.dragging_element or self.resizing_element
            if moved_element:
                new_state = self._snapshot_element(moved_element)
                if new_state != self._undo_pre_state:
                    cmd = MoveResizeCommand(moved_element, self._undo_pre_state, new_state)
                    self.undo_manager.push_command(cmd)
            self._undo_pre_state = None

        # Update properties panel after resize to reflect new values
        self._update_properties_panel()

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
        
        # Reset rotation drag flags
        self.rotating_element = None

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

        # Check if hovering over a gridline
        if self.gridlines_visible:
            gl = self._hit_test_gridline(x, y)
            if gl is not None:
                self.canvas.set_cursor(
                    Gdk.Cursor.new_from_name("row-resize" if gl[0] == "h" else "col-resize", None)
                )
                return

        handle_size = 8 / scale

        # Check if hovering over rotation handle
        if (self.rotation_mode and self.selected_elements and
            self.selected_elements[0].type in (ElementType.TEXT, ElementType.TEXTAREA)):
            element = self.selected_elements[0]
            rot_hx, rot_hy = self._rotation_handle_page_pos(element, scale)
            handle_radius = 10 / scale
            if ((page_x - rot_hx) ** 2 + (page_y - rot_hy) ** 2) <= handle_radius ** 2:
                self.canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
                return

        # Check if hovering over selected element
        if self.selected_elements:
            element = self.selected_elements[0]
            
            if self.selection_mode == 'image' and (element.type in (ElementType.PANEL, ElementType.CUSTOM_PANEL, ElementType.CIRCLE_PANEL)) and element.properties.get("image"):
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
                # Check for speech bubble tail handles first (hand cursor)
                if element.type == ElementType.SPEECH_BUBBLE:
                    tail_tip_x = element.properties.get("tail_tip_x", element.width / 2)
                    tail_tip_y = element.properties.get("tail_tip_y", element.height + 50)
                    tail_px = element.x + tail_tip_x
                    tail_py = element.y + tail_tip_y
                    if (abs(page_x - tail_px) < handle_size and
                        abs(page_y - tail_py) < handle_size):
                        self.canvas.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
                        return

                    # Check tail base handle for spline bubbles
                    control_points = element.properties.get("control_points")
                    if control_points:
                        scaled_pts = [(element.x + px, element.y + py) for px, py in control_points]
                        tail_base_t = element.properties.get("tail_base_t", 0.75)
                        base_pos = self._eval_bubble_curve_at_t(scaled_pts, tail_base_t)
                        if (abs(page_x - base_pos[0]) < handle_size and
                            abs(page_y - base_pos[1]) < handle_size):
                            self.canvas.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
                            return

                        # Check control point handles in edit mode
                        if element == self.edit_mode_element:
                            for px, py in scaled_pts:
                                if (abs(page_x - px) < handle_size and
                                    abs(page_y - py) < handle_size):
                                    self.canvas.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
                                    return

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
        
        # Not hovering over any element — default cursor
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
    
    def _on_add_h_gridline(self, button):
        """Add a horizontal gridline at center of page."""
        if self.current_page:
            self.project.gridlines_h.append(self.current_page.height / 2)
            self.canvas.queue_draw()

    def _on_add_v_gridline(self, button):
        """Add a vertical gridline at center of page."""
        if self.current_page:
            self.project.gridlines_v.append(self.current_page.width / 2)
            self.canvas.queue_draw()

    def _on_toggle_gridlines(self, button):
        """Toggle gridline visibility."""
        self.gridlines_visible = button.get_active()
        self.canvas.queue_draw()

    def _on_clear_gridlines(self, button):
        """Remove all gridlines."""
        if self.current_page:
            self.project.gridlines_h.clear()
            self.project.gridlines_v.clear()
            self.canvas.queue_draw()

    def _hit_test_gridline(self, canvas_x, canvas_y):
        """Check if canvas coordinates are near a gridline. Returns ("h"|"v", index) or None."""
        if not self.current_page:
            return None
        scale = self.zoom_level / 100.0
        padding = 100
        x_offset = padding + self.pan_offset_x
        y_offset = padding + self.pan_offset_y
        hit_dist = 6  # pixels on screen

        for i, gy in enumerate(self.project.gridlines_h):
            screen_y = y_offset + gy * scale
            if abs(canvas_y - screen_y) <= hit_dist:
                # Check within page width
                if x_offset <= canvas_x <= x_offset + self.current_page.width * scale:
                    return ("h", i)

        for i, gx in enumerate(self.project.gridlines_v):
            screen_x = x_offset + gx * scale
            if abs(canvas_x - screen_x) <= hit_dist:
                # Check within page height
                if y_offset <= canvas_y <= y_offset + self.current_page.height * scale:
                    return ("v", i)

        return None

    def _snap_to_gridlines(self, element):
        """Snap element edges to nearby gridlines and page boundaries. Modifies element.x/y in place."""
        if not self.current_page:
            return
        threshold = self.gridline_snap_threshold

        # Element edges
        left = element.x
        right = element.x + element.width
        top = element.y
        bottom = element.y + element.height
        cx = element.x + element.width / 2
        cy = element.y + element.height / 2

        # Page boundaries to snap to
        page_w = self.current_page.width
        page_h = self.current_page.height
        snap_v = [0, page_w]
        snap_h = [0, page_h]

        # Include gridlines if visible
        if self.gridlines_visible:
            snap_v.extend(self.project.gridlines_v)
            snap_h.extend(self.project.gridlines_h)

        # Snap to vertical lines (affect x position)
        best_dx = None
        for gx in snap_v:
            for edge in [left, right, cx]:
                d = gx - edge
                if abs(d) <= threshold and (best_dx is None or abs(d) < abs(best_dx)):
                    best_dx = d
        if best_dx is not None:
            element.x += best_dx

        # Snap to horizontal lines (affect y position)
        best_dy = None
        for gy in snap_h:
            for edge in [top, bottom, cy]:
                d = gy - edge
                if abs(d) <= threshold and (best_dy is None or abs(d) < abs(best_dy)):
                    best_dy = d
        if best_dy is not None:
            element.y += best_dy

    def _snap_resize_candidates(self, new_x, new_y, new_width, new_height, handle):
        """Snap candidate resize dimensions to gridlines. Returns (x, y, w, h) with snapping applied."""
        if not self.current_page:
            return new_x, new_y, new_width, new_height
        threshold = self.gridline_snap_threshold

        page_w = self.current_page.width
        page_h = self.current_page.height
        snap_v = [0, page_w]
        snap_h = [0, page_h]
        if self.gridlines_visible:
            snap_v.extend(self.project.gridlines_v)
            snap_h.extend(self.project.gridlines_h)

        snap_left = handle in ('top-left', 'bottom-left')
        snap_right = handle in ('top-right', 'bottom-right')
        snap_top = handle in ('top-left', 'top-right')
        snap_bottom = handle in ('bottom-left', 'bottom-right')

        if snap_left:
            best = None
            for gx in snap_v:
                d = gx - new_x
                if abs(d) <= threshold and (best is None or abs(d) < abs(best)):
                    best = d
            if best is not None:
                new_x += best
                new_width -= best
        elif snap_right:
            right = new_x + new_width
            best = None
            for gx in snap_v:
                d = gx - right
                if abs(d) <= threshold and (best is None or abs(d) < abs(best)):
                    best = d
            if best is not None:
                new_width += best

        if snap_top:
            best = None
            for gy in snap_h:
                d = gy - new_y
                if abs(d) <= threshold and (best is None or abs(d) < abs(best)):
                    best = d
            if best is not None:
                new_y += best
                new_height -= best
        elif snap_bottom:
            bottom = new_y + new_height
            best = None
            for gy in snap_h:
                d = gy - bottom
                if abs(d) <= threshold and (best is None or abs(d) < abs(best)):
                    best = d
            if best is not None:
                new_height += best

        return new_x, new_y, new_width, new_height

    def _get_image_snap_lines(self, element):
        """Get snap lines for image-in-panel operations (panel edges + gridlines in panel-relative coords)."""
        threshold = self.gridline_snap_threshold
        # Panel edges (in panel-relative coordinates, i.e. offset space)
        snap_v = [0, element.width]
        snap_h = [0, element.height]
        # Gridlines converted to panel-relative coordinates
        if self.gridlines_visible:
            for gx in self.project.gridlines_v:
                snap_v.append(gx - element.x)
            for gy in self.project.gridlines_h:
                snap_h.append(gy - element.y)
        return snap_v, snap_h, threshold

    def _snap_image_in_panel(self, element):
        """Snap image edges to panel edges and gridlines while moving image inside panel."""
        snap_v, snap_h, threshold = self._get_image_snap_lines(element)

        offset_x = element.properties.get("image_offset_x", 0)
        offset_y = element.properties.get("image_offset_y", 0)
        img_w = element.properties.get("image_width", element.width)
        img_h = element.properties.get("image_height", element.height)

        # Image edges in panel-relative space
        left = offset_x
        right = offset_x + img_w
        cx = offset_x + img_w / 2

        best_dx = None
        for gx in snap_v:
            for edge in [left, right, cx]:
                d = gx - edge
                if abs(d) <= threshold and (best_dx is None or abs(d) < abs(best_dx)):
                    best_dx = d
        if best_dx is not None:
            element.properties["image_offset_x"] = offset_x + best_dx

        top = offset_y
        bottom = offset_y + img_h
        cy = offset_y + img_h / 2

        best_dy = None
        for gy in snap_h:
            for edge in [top, bottom, cy]:
                d = gy - edge
                if abs(d) <= threshold and (best_dy is None or abs(d) < abs(best_dy)):
                    best_dy = d
        if best_dy is not None:
            element.properties["image_offset_y"] = offset_y + best_dy

    def _snap_image_resize_in_panel(self, element, aspect_ratio):
        """Snap image edges to panel edges and gridlines while resizing image inside panel."""
        snap_v, snap_h, threshold = self._get_image_snap_lines(element)

        offset_x = element.properties.get("image_offset_x", 0)
        offset_y = element.properties.get("image_offset_y", 0)
        img_w = self.temp_image_width
        img_h = self.temp_image_height

        # Check all four image edges for snap
        right = offset_x + img_w
        bottom = offset_y + img_h

        best_dw = None
        # Snap right edge
        for gx in snap_v:
            d = gx - right
            if abs(d) <= threshold and (best_dw is None or abs(d) < abs(best_dw)):
                best_dw = d
        # Snap left edge
        for gx in snap_v:
            d = gx - offset_x
            if abs(d) <= threshold and (best_dw is None or abs(d) < abs(best_dw)):
                best_dw = -d  # shrink width

        best_dh = None
        # Snap bottom edge
        for gy in snap_h:
            d = gy - bottom
            if abs(d) <= threshold and (best_dh is None or abs(d) < abs(best_dh)):
                best_dh = d
        # Snap top edge
        for gy in snap_h:
            d = gy - offset_y
            if abs(d) <= threshold and (best_dh is None or abs(d) < abs(best_dh)):
                best_dh = -d

        # Pick the snap that requires the smallest proportional change (maintain aspect ratio)
        if best_dw is not None and best_dh is not None:
            if abs(best_dw) / max(img_w, 1) <= abs(best_dh) / max(img_h, 1):
                new_w = img_w + best_dw
                new_h = new_w / aspect_ratio
            else:
                new_h = img_h + best_dh
                new_w = new_h * aspect_ratio
        elif best_dw is not None:
            new_w = img_w + best_dw
            new_h = new_w / aspect_ratio
        elif best_dh is not None:
            new_h = img_h + best_dh
            new_w = new_h * aspect_ratio
        else:
            return

        if new_w > 20 and new_h > 20:
            self.temp_image_width = new_w
            self.temp_image_height = new_h

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
