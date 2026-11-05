import os
import shutil
import stat
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver
from webdriver_manager.chrome import ChromeDriverManager

from autoe2e.utils import AbstractSingleton
from autoe2e.utils import logger
from autoe2e.crawler.config import Config


# TODO: if the connection is closed create a new driver
class DriverContainer(AbstractSingleton):
    def __init__(self, config: Config):
        options = Options()
        browser_path = os.getenv("CHROME_BINARY")
        if browser_path:
            if not Path(browser_path).is_file():
                raise FileNotFoundError(
                    f"CHROME_BINARY does not point to a browser executable: {browser_path}"
                )
        else:
            browser_path = next(
                (
                    path
                    for executable in ("google-chrome", "chromium", "chromium-browser")
                    if (path := shutil.which(executable))
                ),
                None,
            )
        if browser_path is None:
            raise FileNotFoundError(
                "Could not find Chrome or Chromium. Install a browser or set CHROME_BINARY."
            )
        options.binary_location = browser_path
        logger.info(f"Using browser binary: {browser_path}")

        headless = os.getenv("AUTOE2E_HEADLESS", "true").strip().lower()
        if headless not in {"true", "false"}:
            raise ValueError("AUTOE2E_HEADLESS must be 'true' or 'false'")
        if headless == "true":
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        remote_url = os.getenv("SELENIUM_REMOTE_URL")
        if remote_url:
            driver = RemoteWebDriver(
                command_executor=remote_url,
                options=options,
            )
        else:
            driver_path = os.getenv("CHROMEDRIVER_PATH")
            configured_driver_path = bool(driver_path)
            if not driver_path:
                driver_path = ChromeDriverManager(
                    driver_version=os.getenv("CHROMEDRIVER_VERSION")
                ).install()
            driver_path = Path(driver_path)
            if driver_path.name != "chromedriver":
                executable = driver_path.parent / "chromedriver"
                if executable.is_file():
                    driver_path = executable
            if not driver_path.is_file():
                raise FileNotFoundError(
                    f"ChromeDriver executable was not found: {driver_path}"
                )
            if not configured_driver_path and not os.access(driver_path, os.X_OK):
                driver_path.chmod(driver_path.stat().st_mode | stat.S_IXUSR)
            if not os.access(driver_path, os.X_OK):
                raise PermissionError(
                    f"ChromeDriver is not executable: {driver_path}"
                )
            driver_path = str(driver_path)
            logger.info(f"Using ChromeDriver: {driver_path}")
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
