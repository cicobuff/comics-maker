from typing import List, Callable, Any
from collections import deque
import copy


class Command:
    """Base class for undo/redo commands."""

    def execute(self):
        """Execute the command."""
        raise NotImplementedError

    def undo(self):
        """Undo the command."""
        raise NotImplementedError


class MoveResizeCommand(Command):
    """Undo/redo for element move or resize operations."""

    def __init__(self, element, old_state: dict, new_state: dict):
        self.element = element
        self.old_state = old_state
        self.new_state = new_state

    def execute(self):
        self._apply(self.new_state)

    def undo(self):
        self._apply(self.old_state)

    def _apply(self, state):
        self.element.x = state["x"]
        self.element.y = state["y"]
        self.element.width = state["width"]
        self.element.height = state["height"]
        self.element.rotation = state.get("rotation", 0)
        if "properties" in state:
            self.element.properties = copy.deepcopy(state["properties"])


class AddElementCommand(Command):
    """Undo/redo for adding an element."""

    def __init__(self, page, element):
        self.page = page
        self.element = element

    def execute(self):
        if self.element not in self.page.elements:
            self.page.add_element(self.element)

    def undo(self):
        self.page.remove_element(self.element)


class RemoveElementCommand(Command):
    """Undo/redo for removing an element."""

    def __init__(self, page, element, index):
        self.page = page
        self.element = element
        self.index = index

    def execute(self):
        self.page.remove_element(self.element)

    def undo(self):
        self.page.elements.insert(self.index, self.element)


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

    def push_command(self, command: Command):
        """Add a command to the undo stack without executing it (already done)."""
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
