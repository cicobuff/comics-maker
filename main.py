#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.core.config import Config
from src.ui.setup_screen import SetupScreen
from src.ui.projects_screen import ProjectsScreen
from src.ui.workspace import WorkspaceWindow


class ComicsMakerApp(Gtk.Application):
    """Main application class."""
    
    def __init__(self):
        super().__init__(
            application_id="com.comicsmaker.app",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.config = Config()
        self.setup_window = None
        self.projects_window = None
        self.workspace_windows = []
    
    def do_activate(self):
        """Activate the application."""
        if not self.config.load():
            self._show_setup_screen()
        else:
            self._show_projects_screen()
    
    def _show_setup_screen(self):
        """Show the initial setup screen."""
        if not self.setup_window:
            self.setup_window = SetupScreen(
                self.config,
                self._on_setup_complete
            )
            self.setup_window.set_application(self)
        self.setup_window.present()
    
    def _on_setup_complete(self):
        """Handle setup completion."""
        self.setup_window = None
        self._show_projects_screen()
    
    def _show_projects_screen(self):
        """Show the projects management screen."""
        if not self.projects_window:
            self.projects_window = ProjectsScreen(
                self.config,
                self._on_project_selected
            )
            self.projects_window.set_application(self)
        self.projects_window.present()
    
    def _on_project_selected(self, project):
        """Handle project selection."""
        workspace = WorkspaceWindow(self, project, self.config)
        self.workspace_windows.append(workspace)
        workspace.present()


def main():
    """Main entry point."""
    app = ComicsMakerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
