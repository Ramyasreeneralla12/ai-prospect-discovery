from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class ThreadsAdapter(PlatformAdapter):
    name = "Threads"
    domain_query = "threads.net"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
