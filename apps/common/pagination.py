from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class SearchProductV2Pagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "per_page"
    max_page_size = 5000

    def get_paginated_response(self, data):
        per_page = self.page.paginator.per_page
        page_number = int(self.request.query_params.get(self.page_query_param, 1))
        bottom = (page_number - 1) * per_page
        top = bottom + per_page

        return Response(
            {
                "total": -1,
                "from": bottom + 1,
                "to": top,
                "per_page": per_page,
                "current_page": self.page.number,
                "next_page": self.page.next_page_number() if self.page.has_next() else None,
                "prev_page": self.page.previous_page_number() if self.page.has_previous() else None,
                "next_page_url": self.get_next_link(),
                "prev_page_url": self.get_previous_link(),
                "data": data,
            }
        )


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "per_page"
    max_page_size = 5000

    def get_page_size(self, request):
        if self.page_size_query_param:
            page_size = min(int(request.query_params.get(self.page_size_query_param, self.page_size)),
                        self.max_page_size)
            if page_size > 0:
                return page_size
            elif page_size == 0:
                return None
            else:
                pass
        return self.page_size

    def get_paginated_response(self, data):
        per_page = self.page.paginator.per_page
        total = self.page.paginator.count
        page_number = int(self.request.query_params.get(self.page_query_param, 1))
        bottom = (page_number - 1) * per_page
        top = bottom + per_page
        if top >= total:
            top = total

        return Response(
            {
                "total": total,
                "from": bottom + 1,
                "to": top,
                "per_page": per_page,
                "current_page": self.page.number,
                "next_page": self.page.next_page_number() if self.page.has_next() else None,
                "prev_page": self.page.previous_page_number() if self.page.has_previous() else None,
                "next_page_url": self.get_next_link(),
                "prev_page_url": self.get_previous_link(),
                "data": data,
            }
        )


class SearchProductPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "per_page"

    def get_page_number(self, request, paginator):
        return request.data.get("page", 1)

    def get_paginated_response(self, data, *args, **kwargs):

        try:
            total_size = self.page.paginator.count
            last_page = not self.page.has_next()
        except AttributeError:
            # TODO: total size might be wrong when there is no result from table, but there are results from amazon
            total_size = 0
            last_page = True

        amazon_search = kwargs.get("amazon_search")
        if amazon_search:
            total_size += kwargs.get("amazon_total_size", 0)
            last_page &= kwargs.get("amazon_last_page", True)

        pagination_meta = {
            "total_size": total_size,
            "last_page": last_page,
            "vendors": [],
        }
        if vendors_meta := self.request.data.get("meta", {}).get("vendors", []):
            pagination_meta["vendors"] = vendors_meta

        if amazon_search:
            amazon_pagination_meta = [vendor_meta for vendor_meta in vendors_meta if vendor_meta["vendor"] == "amazon"]
            if amazon_pagination_meta:
                amazon_pagination_meta[0]["page"] = kwargs.get("amazon_page")
                amazon_pagination_meta[0]["last_page"] = kwargs.get("amazon_last_page")
            else:
                pagination_meta["vendors"].append(
                    {
                        "vendor": "amazon",
                        "page": kwargs.get("amazon_page"),
                        "last_page": kwargs.get("amazon_last_page"),
                    }
                )

        return Response(
            {
                "meta": pagination_meta,
                "products": data,
            }
        )
