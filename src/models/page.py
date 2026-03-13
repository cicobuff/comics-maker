from typing import List, Dict, Any, Optional
import uuid
from .element import Element


class Page:
    def __init__(self, width: int = 1536, height: int = 2048):
        self.id = str(uuid.uuid4())
        self.width = width
        self.height = height
        self.elements: List[Element] = []
        
    def add_element(self, element: Element):
        """Add an element to the page."""
        self.elements.append(element)
        self._update_layers()
    
    def remove_element(self, element: Element):
        """Remove an element from the page."""
        if element in self.elements:
            self.elements.remove(element)
            self._update_layers()
    
    def get_element_at(self, x: float, y: float) -> Optional[Element]:
        """Get the topmost element at given coordinates."""
        for element in reversed(self.elements):
            if element.contains_point(x, y):
                return element
        return None
    
    def bring_to_front(self, element: Element):
        """Bring element to front."""
        if element in self.elements:
            self.elements.remove(element)
            self.elements.append(element)
            self._update_layers()
    
    def send_to_back(self, element: Element):
        """Send element to back."""
        if element in self.elements:
            self.elements.remove(element)
            self.elements.insert(0, element)
            self._update_layers()
    
    def bring_forward(self, element: Element):
        """Bring element one layer forward."""
        if element in self.elements:
            idx = self.elements.index(element)
            if idx < len(self.elements) - 1:
                self.elements[idx], self.elements[idx + 1] = self.elements[idx + 1], self.elements[idx]
                self._update_layers()
    
    def send_backward(self, element: Element):
        """Send element one layer backward."""
        if element in self.elements:
            idx = self.elements.index(element)
            if idx > 0:
                self.elements[idx], self.elements[idx - 1] = self.elements[idx - 1], self.elements[idx]
                self._update_layers()
    
    def _update_layers(self):
        """Update layer values based on element order."""
        for i, element in enumerate(self.elements):
            element.layer = i
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert page to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "elements": [e.to_dict() for e in self.elements],
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Page':
        """Create page from dictionary."""
        page = Page(data.get("width", 1536), data.get("height", 2048))
        page.id = data["id"]
        page.elements = [Element.from_dict(e) for e in data.get("elements", [])]
        return page
