import time
import traceback
from typing import Any, Self

from selenium.webdriver.remote.webdriver import WebDriver

from autoe2e.crawler.config import Config
from autoe2e.crawler.state import State, StateMachine
from autoe2e.crawler.action import Action
from autoe2e.utils import Queue, logger


class CrawlContext:
    def __init__(self):
        # change to config later
        self.config: Config | None = None
        self.driver: WebDriver | None = None
        self.crawl_queue: Queue[State] = Queue()
        self.state_machine: StateMachine = StateMachine()
        self.temp_vars: dict = {}
    
    
    def set_config(self, config: Config) -> Self:
        if self.config is not None:
            raise ValueError('config is already set')
        self.config = config
        return self
    
    
    def set_driver(self, driver: WebDriver) -> Self:
        if self.driver is not None:
            raise ValueError('driver is already set')
        self.driver = driver
        return self

    
    def load_state(self, state: State) -> None:
        state_id = state.get_id()
        actions = state.crawl_path.get_actions()
        started_at = time.perf_counter()
        phase = 'opening base URL'
        logger.info(
            f'Starting state replay: state={state_id}, '
            f'url={self.config.base_url}, actions={len(actions)}'
        )

        try:
            self.driver.get(self.config.base_url)
            logger.info(
                f'Opened base URL in {time.perf_counter() - started_at:.2f}s'
            )

            for index, action in enumerate(actions, start=1):
                phase = (
                    f'replaying action {index}/{len(actions)} '
                    f'(type={action.get_type().get_value()}, id={action.get_id()})'
                )
                action_started_at = time.perf_counter()
                logger.info(f'Starting state replay {phase}')
                action.execute(self.driver)
                logger.info(
                    f'Completed state replay action {index}/{len(actions)} '
                    f'in {time.perf_counter() - action_started_at:.2f}s'
                )

            logger.info(
                f'Completed state replay: state={state_id}, '
                f'actions={len(actions)}, '
                f'duration={time.perf_counter() - started_at:.2f}s'
            )
        except Exception as error:
            logger.error(
                'State replay failed',
                f'state={state_id}, phase={phase}, '
                f'duration={time.perf_counter() - started_at:.2f}s, '
                f'error={error!r}\n{traceback.format_exc()}'
            )
            raise
    
    
    def create_state_from_driver(self, actions: list[Action]) -> State:
        state: State = State(
            url=self.driver.current_url,
            dom=self.driver.page_source,
            actions=actions
        )
        for action in state.get_actions():
            action.set_parent_state_id(state.get_id())
        return state
    
    
    def set_temp_var(self, key: str, value: Any) -> Self:
        self.temp_vars[key] = value
        return self
    
    
    def get_temp_var(self, key: str) -> Any:
        return self.temp_vars.get(key, None)
    
    
    def reset_temp_var(self, key: str) -> Self:
        self.temp_vars.pop(key, None)
        return self
    
    
    def clear_temp_vars(self) -> Self:
        self.temp_vars = {}
        return self
