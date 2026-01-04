from typing import List, Callable, Any
from collections import deque


class Command:
    """Base class for undo/redo commands."""
    
    def execute(self):
        """Execute the command."""
        raise NotImplementedError
    
    def undo(self):
        """Undo the command."""
        raise NotImplementedError


class UndoManager:
    """Manages undo/redo operations."""
    
    def __init__(self, max_size: int = 999):
        self.max_size = max_size
        self.undo_stack: deque = deque(maxlen=max_size)
        self.redo_stack: deque = deque(maxlen=max_size)
    
    def execute_command(self, command: Command):
        """Execute a command and add it to undo stack."""
        command.execute()
        self.undo_stack.append(command)
        self.redo_stack.clear()
    
    def undo(self) -> bool:
        """Undo the last command. Returns True if successful."""
        if not self.can_undo():
            return False
        
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        return True
    
    def redo(self) -> bool:
        """Redo the last undone command. Returns True if successful."""
        if not self.can_redo():
            return False
        
        command = self.redo_stack.pop()
        command.execute()
        self.undo_stack.append(command)
        return True
    
    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return len(self.undo_stack) > 0
    
    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return len(self.redo_stack) > 0
    
    def clear(self):
        """Clear all undo/redo history."""
        self.undo_stack.clear()
        self.redo_stack.clear()
