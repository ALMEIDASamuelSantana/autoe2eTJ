import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from autoe2e.utils import AbstractSingleton
from autoe2e.crawler.config import Config


def _resolve_chromedriver_path(driver_path: str | None) -> str:
    if driver_path:
        candidate = Path(driver_path)
        if candidate.exists():
            if candidate.is_dir():
                chromedriver = candidate / 'chromedriver'
                if chromedriver.exists() and os.access(chromedriver, os.X_OK):
                    return str(chromedriver)
            elif candidate.name == 'chromedriver' and os.access(candidate, os.X_OK):
                return str(candidate)
            elif candidate.name != 'chromedriver' and candidate.parent.exists():
                sibling = candidate.parent / 'chromedriver'
                if sibling.exists() and os.access(sibling, os.X_OK):
                    return str(sibling)

    installed_path = ChromeDriverManager(
        driver_version=os.getenv('CHROMEDRIVER_VERSION')
    ).install()
    candidate = Path(installed_path)

    if candidate.name != 'chromedriver':
        search_root = candidate.parent if candidate.exists() else candidate
        if search_root.exists():
            for possible in search_root.rglob('chromedriver'):
                if possible.is_file() and os.access(possible, os.X_OK):
                    return str(possible)

    if candidate.exists() and candidate.name == 'chromedriver' and os.access(candidate, os.X_OK):
        return str(candidate)

    return installed_path


# TODO: if the connection is closed create a new driver
class DriverContainer(AbstractSingleton):
    def __init__(self, config: Config):
        options = Options()
        options.binary_location = os.getenv('CHROME_BINARY', '/usr/bin/google-chrome')
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        remote_url = os.getenv('SELENIUM_REMOTE_URL')
        if remote_url:
            driver = RemoteWebDriver(
                command_executor=remote_url,
                options=options,
            )
        else:
            driver_path = os.getenv('CHROMEDRIVER_PATH')
            if not driver_path:
                driver_path = _resolve_chromedriver_path(driver_path)
            driver = webdriver.Chrome(
                service=Service(driver_path),
                options=options,
            )
        # driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()))
        # wait for elements to load on page if necessary
        # driver.implicitly_wait(10)
        self.driver = driver

    def get_driver(self) -> WebDriver:
        return self.driver


def get_driver_container(config: Config) -> DriverContainer:
    driver_container = DriverContainer(config)
    return driver_container
