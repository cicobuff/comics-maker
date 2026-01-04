from typing import Dict, Any, Optional
from enum import Enum
import uuid


class ElementType(Enum):
    PANEL = "panel"
    CUSTOM_PANEL = "custom_panel"
    SHAPE = "shape"
    TEXTAREA = "textarea"
    SPEECH_BUBBLE = "speech_bubble"


class Element:
    def __init__(self, element_type: ElementType, x: float, y: float, 
                 width: float, height: float, **properties):
        self.id = str(uuid.uuid4())
        self.type = element_type
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.rotation = 0
        self.layer = 0
        self.properties = properties
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert element to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "layer": self.layer,
            "properties": self.properties
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Element':
        """Create element from dictionary."""
        element_type = ElementType(data["type"])
        element = Element(
            element_type,
            data["x"],
            data["y"],
            data["width"],
            data["height"],
            **data.get("properties", {})
        )
        element.id = data["id"]
        element.rotation = data.get("rotation", 0)
        element.layer = data.get("layer", 0)
        return element
    
    def contains_point(self, px: float, py: float) -> bool:
        """Check if a point is inside this element."""
        return (self.x <= px <= self.x + self.width and 
                self.y <= py <= self.y + self.height)
