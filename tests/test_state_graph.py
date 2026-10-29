from types import SimpleNamespace
from unittest.mock import Mock

from autoe2e.crawler.action import CandidateActionExtractor
from autoe2e.crawler.crawl_context import CrawlContext
from autoe2e.crawler.state.state_graph import StateGraph
from autoe2e.init_utils import initialize_variables


class GraphState:
    def __init__(self, state_id: str, dom: str):
        self.state_id = state_id
        self.dom = dom

    def get_id(self) -> str:
        return self.state_id


def test_contains_state_matches_id_or_dom() -> None:
    graph: StateGraph[GraphState, object] = StateGraph()
    original = GraphState('state-1', '<main>content</main>')
    graph.add_state(original)

    assert graph.contains_state('state-1', '<main>different</main>')
    assert graph.contains_state('state-2', '<main>content</main>')
    assert not graph.contains_state('state-2', '<main>different</main>')


def test_dom_index_tracks_initial_state_and_reset() -> None:
    graph: StateGraph[GraphState, object] = StateGraph()
    initial = GraphState('initial', '<main>initial</main>')
    graph.set_initial_state(initial)

    assert graph.contains_state('other-id', '<main>initial</main>')

    graph.reset()

    assert not graph.contains_state('initial', '<main>initial</main>')


def test_initialize_variables_registers_initial_state(monkeypatch) -> None:
    crawl_context = CrawlContext()
    crawl_context.set_config(SimpleNamespace(base_url='http://localhost'))
    crawl_context.set_driver(Mock(current_url='http://localhost', page_source='<main />'))
    monkeypatch.setattr(
        CandidateActionExtractor,
        'extract_candidate_actions',
        staticmethod(lambda driver: [])
    )

    initialize_variables(crawl_context)

    initial_state = crawl_context.state_machine.state_graph.get_initial_state()
    assert crawl_context.state_machine.state_graph.contains_state(
        initial_state.get_id(),
        initial_state.dom
    )
    assert crawl_context.crawl_queue.dequeue() is initial_state
