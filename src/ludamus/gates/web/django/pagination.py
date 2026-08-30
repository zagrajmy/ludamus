"""Page-neutral pagination: the size policy, the `Page`, and the context it needs.

Rendered by `components/_pagination.html`. Nothing here is panel-specific — the
organizer tables were just the first callers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.core.paginator import Page, Paginator

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from django.http import HttpRequest

PAGE_SIZES = (10, 20, 50, 100)
DEFAULT_PAGE_SIZE = 20


class PaginationContext[T](TypedDict):
    page_obj: Page[T]
    page_sizes: list[int]


def _page_size(request: HttpRequest) -> int:
    raw = request.GET.get("page_size", "")
    return int(raw) if raw.isdigit() and int(raw) in PAGE_SIZES else DEFAULT_PAGE_SIZE


def _context[T](page_obj: Page[T]) -> PaginationContext[T]:
    # The sizes travel with the page so the picker can't drift from the
    # sizes the paginator actually honours.
    return {"page_obj": page_obj, "page_sizes": list(PAGE_SIZES)}


def pagination_context[T](
    request: HttpRequest, items: Sequence[T]
) -> PaginationContext[T]:
    paginator = Paginator(items, _page_size(request))
    return _context(paginator.get_page(request.GET.get("page")))


def windowed_pagination_context[T](
    request: HttpRequest, *, total: int, window: Callable[[int, int], Sequence[T]]
) -> PaginationContext[T]:
    # For lists too long to hand over whole: the page arithmetic runs against a
    # count-only stand-in, then `window(limit, offset)` fetches just the rows
    # that page shows.
    size = _page_size(request)
    numbers = Paginator(range(total), size).get_page(request.GET.get("page"))
    rows = window(size, max(numbers.start_index() - 1, 0))
    return _context(Page(rows, numbers.number, numbers.paginator))
