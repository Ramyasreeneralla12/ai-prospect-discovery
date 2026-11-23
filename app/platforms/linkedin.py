from app.platforms.base import PlatformAdapter
from app.utils.validators import platform_for_url

class LinkedInAdapter(PlatformAdapter):
    name = "LinkedIn"
    domain_query = "linkedin.com/in"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
