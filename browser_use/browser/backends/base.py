from abc import ABC, abstractmethod

class BrowserBackend(ABC):
    @abstractmethod
    async def launch(self): pass
    @abstractmethod
    async def new_page(self, url: str): pass
    @abstractmethod
    async def navigate(self, page_id: str, url: str): pass
    @abstractmethod
    async def get_dom_snapshot(self, page_id: str): pass
    @abstractmethod
    async def get_ax_tree(self, page_id: str): pass
    @abstractmethod
    async def screenshot(self, page_id: str): pass
    @abstractmethod
    async def click(self, page_id: str, selector: str = None, x: int = None, y: int = None): pass
    @abstractmethod
    async def type_text(self, page_id: str, selector: str, text: str): pass
