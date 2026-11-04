import pytest

from autoe2e.utils import Stack


def test_stack_pops_states_in_depth_first_order() -> None:
    graph = {
        'root': ['left', 'right'],
        'left': ['left-child'],
        'right': ['right-child'],
        'left-child': [],
        'right-child': [],
    }
    stack: Stack[str] = Stack()
    stack.push('root')
    visited = []

    while stack:
        state = stack.pop()
        visited.append(state)
        for child in graph[state]:
            stack.push(child)

    assert visited == ['root', 'right', 'right-child', 'left', 'left-child']


def test_pop_from_empty_stack_raises() -> None:
    with pytest.raises(IndexError, match='pop from empty stack'):
        Stack().pop()
