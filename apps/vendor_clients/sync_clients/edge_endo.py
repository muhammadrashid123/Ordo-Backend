from typing import Optional

from aiohttp import ClientResponse

from apps.vendor_clients import types
from apps.vendor_clients.headers.edge_endo import LOGIN_HEADERS, LOGIN_PAGE_HEADERS
from apps.vendor_clients.sync_clients.base import BaseClient


class EdgeEndoClient(BaseClient):
    VENDOR_SLUG = "edge_endo"

    def get_login_form(self):
        login_dom = self.get_response_as_dom(
            url="https://store.edgeendo.com/login.aspx",
            headers=LOGIN_PAGE_HEADERS,
        )
        login_dom.xpath('//input[@name="_TSM_HiddenField_"]/@value').extract()
        hidden_field = login_dom.xpath('//input[@name="_TSM_HiddenField_"]/@value').extract_first()
        event_target = login_dom.xpath('//input[@name="__EVENTTARGET"]/@value').extract_first()
        event_argument = login_dom.xpath('//input[@name="__EVENTARGUMENT"]/@value').extract_first()
        view_state = login_dom.xpath('//input[@name="__VIEWSTATE"]/@value').extract_first()
        view_state_generator = login_dom.xpath('//input[@name="__VIEWSTATEGENERATOR"]/@value').extract_first()
        return {
            "hidden_field": hidden_field,
            "event_target": event_target,
            "event_argument": event_argument,
            "view_state": view_state,
            "view_state_generator": view_state_generator,
        }

    def get_login_data(self, *args, **kwargs) -> Optional[types.LoginInformation]:
        form = self.get_login_form()
        return {
            "url": "https://store.edgeendo.com/login.aspx",
            "headers": LOGIN_HEADERS,
            "data": {
                "ctl00$ctl00$tsmScripts": "",
                "_TSM_HiddenField_": form["hidden_field"],
                "__EVENTTARGET": form["event_target"],
                "__EVENTARGUMENT": form["event_argument"],
                "__VIEWSTATE": form["view_state"],
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$txtEmail": self.username,
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$vceValid_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$emlLogin$vceRequired_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$txtRestricted": self.password,
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceRegExp_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceLength_ClientState": "",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$pwdLogin$rtbPassword$vceRequired_ClientState": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartProductID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartSKUID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartQuantity": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartWriteInIDs": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartWriteInValues": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartBidPrice": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartShipTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartNewShipTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartGiftMessage": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartGiftWrap": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartFulfillmentMethod": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartPickupAt": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartEmailTo": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartSubscriptionID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartExpressOrder": "",
                "ctl00$ctl00$cphMain$ctl00$hfManualCartPostBack": "",
                "ctl00$ctl00$cphMain$ctl00$hfRemoveCartProductIndex": "",
                "ctl00$ctl00$cphMain$ctl00$hfEditQuantityNewValue": "",
                "ctl00$ctl00$cphMain$ctl00$hfEditQuantityCartProductIndex": "",
                "ctl00$ctl00$cphMain$ctl00$hfReorderID": "",
                "ctl00$ctl00$cphMain$ctl00$hfProductSharingDiscountID": "",
                "ctl00$ctl00$cphMain$ctl00$hfCartRefresh": "",
                "__VIEWSTATEGENERATOR": form["view_state_generator"],
                "__ASYNCPOST": "true",
                "ctl00$ctl00$cphMain$cphMain$lfBtoC$btnCustomerLogin": "Log In Securely",
            },
        }

    def check_authenticated(self, response: ClientResponse) -> bool:
        text = response.text
        return "CustomerID" in text
