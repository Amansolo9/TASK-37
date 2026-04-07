"""Pagination helper for SQLAlchemy queries."""

from flask import request
from dataclasses import dataclass


@dataclass
class PaginationResult:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self):
        if self.per_page == 0:
            return 0
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else None

    @property
    def next_num(self):
        return self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, right_edge=2, left_current=2, right_current=3):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current <= num <= self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate_query(query, page=None, per_page=None, default_per_page=50):
    if page is None:
        page = request.args.get("page", 1, type=int)
    if per_page is None:
        per_page = request.args.get("per_page", default_per_page, type=int)
    page = max(1, page)
    per_page = min(max(1, per_page), 200)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return PaginationResult(items=items, page=page, per_page=per_page, total=total)
