from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class FacebookAdapter(PlatformAdapter):
    name = "Facebook"
    domain_query = "facebook.com"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
