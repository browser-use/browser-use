# centralize imports for browser typing

import sys

from patchright._impl._errors import TargetClosedError as PatchrightTargetClosedError
from patchright.async_api import Browser as PatchrightBrowser
from patchright.async_api import BrowserContext as PatchrightBrowserContext
from patchright.async_api import ElementHandle as PatchrightElementHandle
from patchright.async_api import FrameLocator as PatchrightFrameLocator
from patchright.async_api import Page as PatchrightPage
from patchright.async_api import Playwright as Patchright
from patchright.async_api import async_playwright as _async_patchright
from playwright._impl._errors import TargetClosedError as PlaywrightTargetClosedError
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightBrowserContext
from playwright.async_api import ElementHandle as PlaywrightElementHandle
from playwright.async_api import FrameLocator as PlaywrightFrameLocator
from playwright.async_api import Page as PlaywrightPage
from playwright.async_api import Playwright as Playwright
from playwright.async_api import async_playwright as _async_playwright

from browser_use.browser.driver_socket import async_driver_socket as _async_driver_socket
from browser_use.browser.generic import Driver as GenericDriver
from browser_use.browser.generic import ElementHandle as GenericElementHandle
from browser_use.browser.generic import FrameLocator as GenericFrameLocator
from browser_use.browser.generic import GenericBrowser, GenericBrowserContext
from browser_use.browser.generic import Page as GenericPage

# Define types to be Union[Patchright, Playwright]
Browser = PatchrightBrowser | PlaywrightBrowser | GenericBrowser
BrowserContext = PatchrightBrowserContext | PlaywrightBrowserContext | GenericBrowserContext
Page = PatchrightPage | PlaywrightPage | GenericPage
ElementHandle = PatchrightElementHandle | PlaywrightElementHandle | GenericElementHandle
FrameLocator = PatchrightFrameLocator | PlaywrightFrameLocator | GenericFrameLocator
Playwright = Playwright
Patchright = Patchright
GenericDriver = GenericDriver
BrowserDriver = Patchright | Playwright | GenericDriver
TargetClosedError = PatchrightTargetClosedError | PlaywrightTargetClosedError

async_patchright = _async_patchright
async_playwright = _async_playwright
async_driver_socket = _async_driver_socket

from playwright._impl._api_structures import (
	ClientCertificate,
	Geolocation,
	HttpCredentials,
	ProxySettings,
	StorageState,
	ViewportSize,
)

# fix pydantic error on python 3.11
# PydanticUserError: Please use `typing_extensions.TypedDict` instead of `typing.TypedDict` on Python < 3.12.
# For further information visit https://errors.pydantic.dev/2.10/u/typed-dict-version
if sys.version_info < (3, 12):
	from typing_extensions import TypedDict

	# convert new-style typing.TypedDict used by playwright to old-style typing_extensions.TypedDict used by pydantic
	ClientCertificate = TypedDict('ClientCertificate', ClientCertificate.__annotations__, total=ClientCertificate.__total__)
	Geolocation = TypedDict('Geolocation', Geolocation.__annotations__, total=Geolocation.__total__)
	ProxySettings = TypedDict('ProxySettings', ProxySettings.__annotations__, total=ProxySettings.__total__)
	ViewportSize = TypedDict('ViewportSize', ViewportSize.__annotations__, total=ViewportSize.__total__)
	HttpCredentials = TypedDict('HttpCredentials', HttpCredentials.__annotations__, total=HttpCredentials.__total__)
	StorageState = TypedDict('StorageState', StorageState.__annotations__, total=StorageState.__total__)
