import os

from ebaysdk.finding import Connection as Finding
from ebaysdk.exception import ConnectionError


class EbaySearch:

    def __init__(self):
        self.ebay_api = Finding(domain=os.getenv("EBAY_DOMAIN"),
                                appid=os.getenv("EBAY_APP_ID"),
                                config_file=None)

    def execute(self, keyword, from_price=None, to_price=None):
        """
        Search for Ebay products by the given keyword
        and return the result in a ordo product format.
        :param to_price: decimal - select products less than equals to this price
        :param from_price: decimal - select products more than equals to this price
        :param keyword: str - the keyword to search products by
        :return: json
        """
        try:
            response = self.ebay_api.execute('findItemsByKeywords', {'keywords': keyword})

            if not response.ok:
                print("Ebay API execution is failed for some reason.")
                return []

            products = []
            dict_data = response.dict()

            pagination_info = dict_data["paginationOutput"]  # Will use later...
            searched_result = dict_data["searchResult"]

            if int(searched_result["_count"]) <= 0:
                return []

            for item in searched_result["item"]:
                item_price = item["sellingStatus"]["convertedCurrentPrice"]["value"]

                if from_price and item_price and float(item_price) < float(from_price):
                    continue
                if to_price and item_price and float(item_price) > float(to_price):
                    continue
                products.append(
                    {
                        "product_id": item["itemId"],
                        "product_unit": "",
                        "name": item["title"],
                        "category": item["primaryCategory"].get("categoryName", ""),
                        "description": "",
                        "url": item["viewItemURL"],
                        "images": [
                            {
                                "image": item["galleryURL"] if item["galleryURL"] else "",
                            }
                        ],
                        "price": item_price,
                        "vendor": "ebay",
                    }
                )
            return products
        except ConnectionError as error:
            print(error)
            print(error.response.dict())
            return []
