from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class XAdapter(PlatformAdapter):
    name = "X"
    domain_query = "x.com"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
