ALL_PRODUCTS_QUERY = """
  query Catalog($includeAllSkus: Boolean = true, $withImages: Boolean = false) {
    allProducts(includeAllSkus: $includeAllSkus) {
      sku
      brandName
      productName
      productFamily
      kitName
      url
      isOrderable
      images @include(if: $withImages) {
        source
        __typename
      }
      __typename
    }
  }
"""

PRODUCT_DETAIL_QUERY = """
    query CatalogItem($skuValues: String!, $withPrice: Boolean = false, $withAccessories: Boolean = false) {
        product(sku: $skuValues) {
            ...baseCatalogDetail
            quantityBreaks @include(if: $withPrice) {
                ...quantityBreakDetail
                __typename
            }
            accessories @include(if: $withAccessories) {
                ...accessoryDetail
                __typename
            }
            __typename
        }
    }

    fragment baseCatalogDetail on Product {
        sku
        brandId
        url
        kitName
        brandName
        productName
        productFamily
        catalogPrice
        customerPrice
        inStock
        isOrderable
        images {
            source
            __typename
        }
        __typename
    }

    fragment quantityBreakDetail on QuantityBreak {
        price
        quantity
        __typename
    }

    fragment accessoryDetail on Product {
        sku
        productFamily
        productName
        kitName
        url
        images {
            source
            __typename
        }
        __typename
    }
"""

GET_ORDERS_QUERY = """
   query GetOrderHeaders($numberOfDays: Int!, $numberOfRows: Int!) {
       orders(numberOfDays: $numberOfDays, numberOfRows: $numberOfRows) {
           id
           orderGuid
           orderNumber
           poNumber
           orderStatus
           orderDate
           shippingAddress {
               id
               __typename
           }
           __typename
       }
   }
"""

GET_ORDER_QUERY = """
    query GetOrderDetailWithTrackingHtml($orderNumber: Int!) {
        orderHtml(orderNumber: $orderNumber) {
            orderDetailWithShippingHtml
            __typename
        }
    }
"""

ADD_CART_QUERY = """
    mutation AddLineItems($input: LineItemsInput!) {
        addLineItems(input: $input) {
            changedLineItems {
            ...CartItemDetail
            __typename
            }
            cart {
            ...CartDetail
            __typename
            }
            __typename
        }
    }

    fragment CartItemDetail on CartLineItem {
        id
        quantity
        linePrice
        autoAddedItem
        product {
            ...baseCatalogDetail
            quantityBreaks {
            ...quantityBreakDetail
            __typename
            }
            __typename
        }
        __typename
    }

    fragment CartDetail on Cart {
        ...CartSummary
        lineItems {
            ...CartItemDetail
            __typename
        }
        __typename
    }

    fragment baseCatalogDetail on Product {
        sku
        brandId
        url
        kitName
        brandName
        productName
        productFamily
        catalogPrice
        customerPrice
        inStock
        isOrderable
        images {
            source
            __typename
        }
        __typename
    }

    fragment quantityBreakDetail on QuantityBreak {
        price
        quantity
        __typename
    }

    fragment CartSummary on Cart {
        id
        poNumber
        subtotal
        total
        __typename
    }
"""

BILLING_QUERY = """
    query GetCustomer($withAddresses: Boolean = false) {
        customer {
            email
            firstName
            lastName
            userGuid
            isAdmin
            addresses @include(if: $withAddresses) {
                ...AddressDetail
                __typename
            }
            __typename
        }
    }

    fragment AddressDetail on Address {
        address1
        address2
        addressType
        city
        country
        id
        postalCode
        primary
        state
        __typename
    }
"""

GET_ORDER_DETAIL_HTML = """
    query GetOrderDetailHtml($orderNumber: Int!) {
        orderHtml(orderNumber: $orderNumber) {
            orderDetailHtml
            __typename
        }
    }
"""
