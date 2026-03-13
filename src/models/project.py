from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import shutil
from datetime import datetime
from .page import Page


class Project:
    def __init__(self, name: str, directory: Path, width: int = 1536, height: int = 2048):
        self.name = name
        self.directory = directory
        self.page_width = width
        self.page_height = height
        self.pages: List[Page] = []
        self.gridlines_h: List[float] = []  # horizontal guideline Y positions (shared across pages)
        self.gridlines_v: List[float] = []  # vertical guideline X positions (shared across pages)
        self.created = datetime.now().isoformat()
        self.modified = datetime.now().isoformat()
        
        self.project_file = directory / "project.comic"
        self.images_dir = directory / "images"
        self.thumbs_dir = directory / "thumbs"
        
    def add_page(self, page: Optional[Page] = None) -> Page:
        """Add a new page to the project."""
        if page is None:
            page = Page(self.page_width, self.page_height)
        self.pages.append(page)
        return page
    
    def remove_page(self, page: Page):
        """Remove a page from the project."""
        if page in self.pages:
            self.pages.remove(page)
    
    def duplicate_page(self, page: Page) -> Page:
        """Duplicate a page."""
        if page in self.pages:
            idx = self.pages.index(page)
            page_data = page.to_dict()
            new_page = Page.from_dict(page_data)
            import uuid
            new_page.id = str(uuid.uuid4())
            for element in new_page.elements:
                element.id = str(uuid.uuid4())
            self.pages.insert(idx + 1, new_page)
            return new_page
        return None
    
    def move_page(self, page: Page, new_index: int):
        """Move page to new position."""
        if page in self.pages:
            self.pages.remove(page)
            self.pages.insert(new_index, page)
    
    def ensure_directories(self):
        """Ensure project directories exist."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(exist_ok=True)
        self.thumbs_dir.mkdir(exist_ok=True)
    
    def save(self):
        """Save project to disk."""
        self.ensure_directories()
        self.modified = datetime.now().isoformat()
        
        project_data = {
            "name": self.name,
            "created": self.created,
            "modified": self.modified,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "pages": [p.to_dict() for p in self.pages],
            "gridlines_h": self.gridlines_h,
            "gridlines_v": self.gridlines_v,
        }
        
        with open(self.project_file, 'w') as f:
            json.dump(project_data, f, indent=2)
    
    @staticmethod
    def load(project_dir: Path) -> 'Project':
        """Load project from disk."""
        project_file = project_dir / "project.comic"
        
        with open(project_file, 'r') as f:
            data = json.load(f)
        
        project = Project(
            data["name"],
            project_dir,
            data.get("page_width", 1536),
            data.get("page_height", 2048)
        )
        project.created = data.get("created", datetime.now().isoformat())
        project.modified = data.get("modified", datetime.now().isoformat())
        project.pages = [Page.from_dict(p) for p in data.get("pages", [])]
        project.gridlines_h = data.get("gridlines_h", [])
        project.gridlines_v = data.get("gridlines_v", [])

        return project
    
    @staticmethod
    def create_new(name: str, projects_dir: Path, template: Optional[Dict] = None) -> 'Project':
        """Create a new project."""
        if template is None:
            template = {"width": 1536, "height": 2048}
        
        project_dir = projects_dir / f"{name}.comicmaker"
        project = Project(name, project_dir, template["width"], template["height"])
        project.ensure_directories()
        project.add_page()
        project.save()
        
        return project
    
    def copy_image_to_project(self, source_path: Path) -> str:
        """Copy an image to the project images directory and return the UUID filename."""
        import uuid
        
        # Ensure images directory exists
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        file_extension = source_path.suffix
        new_filename = f"{uuid.uuid4()}{file_extension}"
        dest_path = self.images_dir / new_filename
        
        shutil.copy2(source_path, dest_path)
        
        return new_filename
