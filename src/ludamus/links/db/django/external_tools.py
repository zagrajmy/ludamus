from urllib.parse import urlsplit

from ludamus.links.db.django.models import ExternalTool
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.external_tools import ExternalToolDTO, ExternalToolRepositoryProtocol


class ExternalToolRepository(ExternalToolRepositoryProtocol):
    @staticmethod
    def read_active(slug: str) -> ExternalToolDTO:
        try:
            tool = ExternalTool.objects.get(slug=slug, is_active=True)
        except ExternalTool.DoesNotExist as exception:
            raise NotFoundError from exception
        return ExternalToolDTO(
            name=tool.name,
            slug=tool.slug,
            url=tool.url,
            # netloc, not hostname: a source without the port matches only
            # port 443. The model validators vet these values.
            frame_hosts=[urlsplit(tool.url).netloc, *tool.allowed_domains.split()],
        )
