from collections import deque
from typing import Generic, TypeVar


T = TypeVar('T')


class Stack(Generic[T]):
    """A stack implemented using deque."""

    def __init__(self):
        self.items: deque[T] = deque()

    def reset(self):
        self.items.clear()

    def is_empty(self) -> bool:
        return not self.items

    def push(self, item: T):
        self.items.append(item)

    def pop(self) -> T:
        if self.is_empty():
            raise IndexError("pop from empty stack")
        return self.items.pop()

    def peek(self) -> T:
        if self.is_empty():
            raise IndexError("peek from empty stack")
        return self.items[-1]

    def __len__(self) -> int:
        return len(self.items)
