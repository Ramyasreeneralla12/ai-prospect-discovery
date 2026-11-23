from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class YouTubeAdapter(PlatformAdapter):
    name = "YouTube"
    domain_query = "youtube.com/@"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
