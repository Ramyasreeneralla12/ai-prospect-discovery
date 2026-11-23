from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class InstagramAdapter(PlatformAdapter):
    name = "Instagram"
    domain_query = "instagram.com"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
