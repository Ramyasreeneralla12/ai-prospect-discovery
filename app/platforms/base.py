from abc import ABC, abstractmethod

from app.schemas import SearchResult
from app.services.search_service import SearchProvider


class PlatformAdapter(ABC):
    name: str
    domain_query: str

    def __init__(self, search: SearchProvider):
        self.search_service = search

    def make_query(self, terms: str, location: str) -> str:
        return f'site:{self.domain_query} "{terms}" {location}'.strip()

    async def discover(self, terms: str, location: str) -> list[SearchResult]:
        return await self.search_service.search(self.make_query(terms, location))

    @abstractmethod
    def accepts(self, url: str) -> bool: ...
