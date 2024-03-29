import uuid

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_recursive.fields import RecursiveField

from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.serializers import VendorLiteSerializer
from apps.common.choices import OrderStatus
from apps.common.serializers import Base64ImageField
from apps.orders.helpers import OfficeProductHelper, OrderHelper

from ..accounts.models import BasisType, OpenDentalKey
from . import models as m


class OfficeProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = m.OfficeProductCategory
        exclude = ("created_at", "updated_at")
        extra_kwargs = {"slug": {"read_only": True}}

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        if self.context.get("with_inventory_count"):
            ret["vendor_ids"] = instance.vendors
            ret["count"] = instance.count

        return ret


class OfficeProductVendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Vendor
        fields = "__all__"

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if self.context.get("with_inventory_count"):
            ret["category_ids"] = instance.categories
            ret["count"] = instance.count
        return ret


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ProductCategory
        fields = (
            "id",
            "name",
            "slug",
        )


class OfficeReadSerializer(serializers.Serializer):
    office_id = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all())


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ProductImage
        fields = ("image",)


class SimpleProductSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    is_inventory = serializers.BooleanField(default=False, read_only=True)

    class Meta:
        model = m.Product
        fields = (
            "id",
            "name",
            "image",
            "is_inventory",
        )

    def get_image(self, instance):
        if instance.vendor is None:
            image = m.ProductImage.objects.filter(product__parent=instance).first()
        else:
            image = instance.images.first()
        if image:
            return image.image


class ChildProductV2Serializer(serializers.ModelSerializer):
    vendor = VendorLiteSerializer()
    category = ProductCategorySerializer()
    images = ProductImageSerializer(many=True, required=False)
    product_price = serializers.DecimalField(decimal_places=2, max_digits=10, read_only=True)
    is_inventory = serializers.BooleanField(default=False, read_only=True)
    product_vendor_status = serializers.CharField(read_only=True)
    last_order_date = serializers.DateField(read_only=True)
    last_order_vendor = serializers.DecimalField(decimal_places=2, max_digits=10, read_only=True)
    nickname = serializers.CharField(max_length=128, allow_null=True)
    # image_url = Base64ImageField()

    last_order_price = serializers.DecimalField(decimal_places=2, max_digits=10, read_only=True)

    class Meta:
        model = m.Product
        fields = (
            "id",
            "vendor",
            "name",
            "nickname",
            # "image_url",
            "product_id",
            "manufacturer_number",
            "category",
            "product_unit",
            "url",
            "images",
            "product_price",
            "is_special_offer",
            "special_price",
            "promotion_description",
            "is_inventory",
            "product_vendor_status",
            "last_order_date",
            "last_order_price",
            "last_order_vendor",
            "sku",
        )
        ordering = ("name",)

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        if hasattr(instance, "office_product") and instance.office_product:
            office_product = instance.office_product[0]
        elif "office_pk" in self.context:
            office_product = instance.office_products.filter(office_id=self.context["office_pk"]).first()
        else:
            office_product = None
        if office_product:
            ret["is_inventory"] = office_product.is_inventory
            ret["product_vendor_status"] = office_product.product_vendor_status
            ret["last_order_date"] = office_product.last_order_date
            ret["last_order_price"] = office_product.last_order_price
            ret["last_order_vendor"] = office_product.product.vendor_id
            ret["nickname"] = office_product.nickname
            ret["price"] = office_product.price
            # ret["image_url"] = instance.office_product[0].image_url

        return ret


class ProductV2Serializer(serializers.ModelSerializer):
    vendor = VendorLiteSerializer()
    category = ProductCategorySerializer()
    images = ProductImageSerializer(many=True, required=False)
    is_inventory = serializers.BooleanField(default=False, read_only=True)
    product_vendor_status = serializers.CharField(read_only=True)
    last_order_date = serializers.DateField(read_only=True)
    last_order_vendor = serializers.DecimalField(decimal_places=2, max_digits=10, read_only=True)
    nickname = serializers.CharField(max_length=128, allow_null=True)
    # image_url = Base64ImageField()

    last_order_price = serializers.DecimalField(decimal_places=2, max_digits=10, read_only=True)

    children = ChildProductV2Serializer(many=True)

    class Meta:
        model = m.Product
        fields = (
            "id",
            "vendor",
            "name",
            "nickname",
            # "image_url",
            "product_id",
            "manufacturer_number",
            "category",
            "product_unit",
            "url",
            "images",
            "is_special_offer",
            "special_price",
            "price",
            "promotion_description",
            "is_inventory",
            "product_vendor_status",
            "last_order_date",
            "last_order_price",
            "last_order_vendor",
            "children",
            "sku",
        )
        ordering = ("name",)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["description"] = instance.description

        children = ret["children"]

        if children:
            last_order_dates = sorted(
                [
                    (child["last_order_date"], child["last_order_price"], child["last_order_vendor"])
                    for child in children
                    if child["is_inventory"]
                ],
                key=lambda x: x[0],
                reverse=True,
            )
            if last_order_dates:
                ret["last_order_date"] = last_order_dates[0][0]
                ret["last_order_price"] = last_order_dates[0][1]
                ret["last_order_vendor"] = last_order_dates[0][2]
        return ret


class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Promotion
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    vendor = VendorLiteSerializer()
    images = ProductImageSerializer(many=True, required=False)
    category = ProductCategorySerializer(read_only=True)
    promotion_description = serializers.CharField(required=False, read_only=True)
    children = serializers.ListSerializer(child=RecursiveField(), required=False, read_only=True)

    def get_fields(self):
        fields = super().get_fields()

        include_children = self.context.get("include_children", False)
        if not include_children:
            fields.pop("children", default=None)

        return fields

    class Meta:
        model = m.Product
        fields = (
            "id",
            "vendor",
            "images",
            "category",
            "children",
            "product_id",
            "name",
            "product_unit",
            "is_special_offer",
            "description",
            "promotion_description",
            "url",
        )


class ProductReadDetailSerializer(serializers.Serializer):
    office_id = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all())
    vendor = serializers.PrimaryKeyRelatedField(queryset=m.Vendor.objects.all())
    product_id = serializers.CharField()
    product_url = serializers.URLField()


class VendorOrderProductSerializer(serializers.ModelSerializer):
    status_display_text = serializers.CharField(source="get_status_display")
    item_inventory = serializers.BooleanField(read_only=True)

    class Meta:
        model = m.VendorOrderProduct
        fields = "__all__"

    def update(self, instance, validated_data):
        with transaction.atomic():
            OfficeBudgetHelper.move_spend_category(
                office=instance.vendor_order.order.office_id,
                date=instance.vendor_order.order.order_date,
                amount=instance.unit_price * instance.quantity,
                from_category=instance.budget_spend_type,
                to_category=validated_data.get("budget_spend_type"),
            )

            vendor_order = instance.vendor_order
            order = vendor_order.order
            new_vendor_order = None
            if "product" in validated_data and instance.product_id != validated_data["product"].id:
                product = validated_data["product"]
                office = instance.vendor_order.order.office
                unit_price = OfficeProductHelper.get_product_price(office=office, product=product)
                validated_data["unit_price"] = unit_price

                new_quantity = instance.quantity
                if "quantity" in validated_data:
                    new_quantity = validated_data["quantity"]

                new_vendor_order = order.vendor_orders.filter(
                    vendor=product.vendor, status=OrderStatus.PENDING_APPROVAL
                ).first()
                new_vendor_order_product = (
                    new_vendor_order.order_products.filter(product_id=product.id).first() if new_vendor_order else None
                )
                if new_vendor_order and vendor_order.id == new_vendor_order.id:
                    instance = super().update(instance, validated_data)
                    OrderHelper.update_vendor_order_totals(vendor_order)
                    return instance

                if new_vendor_order_product:
                    order.total_items -= 1
                    new_vendor_order_product.quantity += new_quantity
                    new_vendor_order_product.save()
                    vendor_order.total_items -= 1
                    instance.delete()
                    if vendor_order.total_items:
                        vendor_order.save()
                    else:
                        vendor_order.delete()
                        order.save()
                    if vendor_order.id:
                        OrderHelper.update_vendor_order_totals(vendor_order)
                    OrderHelper.update_vendor_order_totals(new_vendor_order)
                    OrderHelper.update_order_totals(order)

                    return new_vendor_order_product
                if new_vendor_order:
                    new_vendor_order.total_items += 1
                    new_vendor_order.save()
                else:
                    random_order_id = f"{uuid.uuid4()}"
                    new_vendor_order = m.VendorOrder.objects.bulk_create(
                        [
                            m.VendorOrder(
                                order=order,
                                vendor=product.vendor,
                                vendor_order_id=random_order_id,
                                total_amount=0,
                                total_items=1,
                                currency=vendor_order.currency,
                                order_date=vendor_order.order_date,
                                status=vendor_order.status,
                                shipping_option=vendor_order.shipping_option,
                            )
                        ]
                    )[0]
                    validated_data["vendor_order"] = new_vendor_order
                vendor_order.total_items -= 1
                if vendor_order.total_items:
                    vendor_order.save()
                else:
                    vendor_order.delete()

            instance = super().update(instance, validated_data)

            if new_vendor_order:
                OrderHelper.update_vendor_order_totals(new_vendor_order)

            if "status" in validated_data:
                if not (
                    m.VendorOrderProduct.objects.filter(vendor_order=vendor_order)
                    .exclude(status__in=[m.ProductStatus.RECEIVED, m.ProductStatus.REJECTED])
                    .exists()
                ):
                    vendor_order.status = OrderStatus.CLOSED
                    vendor_order.save()
                else:
                    vendor_order.status = OrderStatus.OPEN
                    vendor_order.save()

                if not (
                    m.VendorOrderProduct.objects.filter(vendor_order__order=order)
                    .exclude(status__in=[m.ProductStatus.RECEIVED, m.ProductStatus.REJECTED])
                    .exists()
                ):
                    order.status = OrderStatus.CLOSED
                    order.save()
                else:
                    order.status = OrderStatus.OPEN
                    order.save()

            if vendor_order.id:
                OrderHelper.update_vendor_order_totals(vendor_order)
            OrderHelper.update_order_totals(order)

            return instance

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["product"] = ProductSerializer(instance.product).data
        ret["order_date"] = instance.vendor_order.order_date

        if hasattr(instance, "updated_unit_price"):
            ret["updated_unit_price"] = instance.updated_unit_price
        else:
            office_product = m.OfficeProduct.objects.filter(
                product_id=instance.product_id, office_id=instance.vendor_order.order.office_id
            ).first()

            if office_product:
                ret["updated_unit_price"] = office_product.price
            else:
                ret["updated_unit_price"] = instance.product.price

        if not ret["status_display_text"]:
            ret["status_display_text"] = "N/A"
        return ret


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Vendor
        fields = "__all__"


class VendorOrderSerializer(serializers.ModelSerializer):
    products = VendorOrderProductSerializer(many=True, source="order_products")
    vendor = VendorLiteSerializer()
    order = serializers.PrimaryKeyRelatedField(read_only=True)
    status_display_text = serializers.CharField(source="get_status_display")
    is_invoice_available = serializers.BooleanField()

    class Meta:
        model = m.VendorOrder
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if data["status_display_text"]:
            data["status_display_text"] = str(data["status_display_text"]).title()
        return data


class OrderSerializer(serializers.ModelSerializer):
    vendor_orders = VendorOrderSerializer(many=True)

    class Meta:
        model = m.Order
        fields = "__all__"


class OrderListSerializer(serializers.ModelSerializer):
    vendors = serializers.SerializerMethodField()

    class Meta:
        model = m.Order
        fields = (
            "id",
            "vendors",
            "total_amount",
            "order_date",
            "status",
            "total_items",
        )

    def get_vendors(self, instance):
        vendors = instance.vendor_orders.select_related("vendor")
        return VendorLiteSerializer([vendor.vendor for vendor in vendors], many=True).data


class OfficeVendorConnectedSerializer(serializers.Serializer):
    office_associated_id = serializers.CharField()
    id = serializers.CharField()
    name = serializers.CharField()
    logo = serializers.CharField()


class TotalSpendSerializer(serializers.Serializer):
    vendor = OfficeVendorConnectedSerializer(read_only=True)
    month = serializers.CharField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class ProductDataSerializer(serializers.Serializer):
    vendor = serializers.PrimaryKeyRelatedField(queryset=m.Vendor.objects.all())
    images = ProductImageSerializer(many=True, required=False)
    product_id = serializers.CharField()
    category = serializers.PrimaryKeyRelatedField(
        queryset=m.ProductCategory.objects.all(), allow_null=True, allow_empty=True
    )
    name = serializers.CharField()
    product_unit = serializers.CharField(allow_null=True, allow_blank=True)
    description = serializers.CharField(allow_null=True, allow_blank=True)
    url = serializers.CharField()


class OfficeProductReadSerializer(serializers.Serializer):
    product = ProductDataSerializer()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)


class CartCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Cart
        fields = "__all__"
        extra_kwargs = {"budget_spend_type": {"required": False}}

    def create(self, attrs):
        office = attrs["office"]
        product = attrs["product"]
        attrs["unit_price"] = OfficeProductHelper.get_product_price(office, product=product)
        if "budget_spend_type" not in attrs or attrs["budget_spend_type"] is None:
            budget = OfficeBudgetHelper.get_or_create_budget(office_id=office.id)
            slug_mapping = OfficeBudgetHelper.get_slug_mapping(budget)
            attrs["budget_spend_type"] = slug_mapping[product.vendor.slug]
        return super().create(attrs)


class CartSerializer(serializers.ModelSerializer):
    # office_product = OfficeProductReadSerializer(write_only=True)
    product = ProductSerializer(read_only=True, required=False)
    promotion = PromotionSerializer(read_only=True, required=False)
    updated_unit_price = serializers.SerializerMethodField()
    item_inventory = serializers.BooleanField(read_only=True)

    # same_products = serializers.SerializerMethodField()
    # office = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all())

    class Meta:
        model = m.Cart
        fields = (
            "id",
            "office",
            "product",
            "quantity",
            "unit_price",
            "updated_unit_price",
            "item_inventory",
            "save_for_later",
            "instant_checkout",
            "promotion",
            "budget_spend_type",
        )

    # def validate(self, attrs):
    #     if not self.instance:
    #         product_id = attrs["office_product"]["product"]["product_id"]
    #         office = attrs["office"]
    #         if m.Cart.objects.filter(office=office, product__product_id=product_id).exists():
    #             raise serializers.ValidationError({"message": "This product is already in your cart"})
    #     return attrs

    # def create(self, validated_data):
    #     with transaction.atomic():
    #         office_product = validated_data.pop("office_product", {})
    #         product_data = office_product.pop("product")
    #         office = validated_data.get("office")
    #         vendor = product_data.pop("vendor")
    #         product_id = product_data.pop("product_id")
    #         images = product_data.pop("images", [])
    #         product, created = m.Product.objects.get_or_create(
    #             vendor=vendor, product_id=product_id, defaults=product_data
    #         )
    #         if created:
    #             product_images_objs = []
    #             for image in images:
    #                 product_images_objs.append(m.ProductImage(product=product, image=image["image"]))
    #             if images:
    #                 m.ProductImage.objects.bulk_create(product_images_objs)

    #         try:
    #             price = office_product.pop("price")
    #             m.OfficeProduct.objects.update_or_create(office=office, product=product, defaults={"price": price})
    #             return m.Cart.objects.create(product=product, **validated_data)
    #         except IntegrityError:
    #             raise serializers.ValidationError({"message": "This product is already in your cart"})

    def get_updated_unit_price(self, cart_product: object) -> object:
        """
        Return the updated product price
        """
        if hasattr(cart_product, "updated_unit_price"):
            return cart_product.updated_unit_price

        updated_product_price = m.OfficeProduct.objects.filter(
            office_id=cart_product.office_id, product_id=cart_product.product_id
        ).values("price")[:1]
        if not updated_product_price:
            updated_product_price = m.Product.objects.filter(id=cart_product.product_id).values("price")[:1]
        return updated_product_price[0]["price"] if updated_product_price else 0

    def to_representation(self, instance):
        # TODO: return sibling products from linked vendor
        ret = super().to_representation(instance)
        try:
            sibling_products = [o for o in instance.product.parent.children.all() if o.id != instance.product_id]
            ret["sibling_products"] = ChildProductV2Serializer(
                sibling_products,
                many=True,
            ).data
        except:
            ret["sibling_products"] = []
        return ret


class OfficeCheckoutStatusUpdateSerializer(serializers.Serializer):
    checkout_status = serializers.ChoiceField(choices=m.OfficeCheckoutStatus.CHECKOUT_STATUS.choices)


class OfficeProductSerializer(serializers.ModelSerializer):
    product_data = ProductSerializer(write_only=True)
    office = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all(), write_only=True)
    office_product_category = serializers.PrimaryKeyRelatedField(queryset=m.OfficeProductCategory.objects.all())
    vendor = serializers.CharField(read_only=True)
    image_url = Base64ImageField()
    last_quantity_ordered = serializers.SerializerMethodField("custom_last_quantity_ordered")
    quantity_on_hand = serializers.SerializerMethodField("custom_quantity_on_hand")
    quantity_to_be_ordered = serializers.SerializerMethodField("custom_quantity_to_be_ordered")

    class Meta:
        model = m.OfficeProduct
        fields = (
            "id",
            "office",
            "product_data",
            "price",
            "office_product_category",
            "is_favorite",
            "is_inventory",
            "nickname",
            "image_url",
            "last_order_date",
            "last_order_price",
            "vendor",
            "last_quantity_ordered",
            "quantity_on_hand",
            "quantity_to_be_ordered",
        )

    def custom_last_quantity_ordered(self, office_product):
        """
        Return the empty data temporary...
        """
        if hasattr(office_product, "last_quantity_ordered"):
            return office_product.last_quantity_ordered
        else:
            quantity_ordered = office_product.product.vendororderproduct_set.order_by("-updated_at").first()
            return quantity_ordered.quantity if quantity_ordered else 0

    def custom_quantity_on_hand(self, office_product):
        """
        Return the empty data temporary...
        """
        return ""

    def custom_quantity_to_be_ordered(self, office_product):
        """
        Return the empty data temporary...
        """
        return ""

    def create(self, validated_data):
        with transaction.atomic():
            product_data = validated_data.pop("product_data")
            vendor = product_data.pop("vendor")
            product_id = product_data.pop("product_id")
            images = product_data.pop("images", [])
            product, created = m.Product.objects.get_or_create(
                vendor=vendor, product_id=product_id, defaults=product_data
            )

            if created:
                product_images_objs = []
                for image in images:
                    product_images_objs.append(m.ProductImage(product=product, image=image))
                if images:
                    m.ProductImage.objects.bulk_create(product_images_objs)

            return m.OfficeProduct.objects.create(product=product, **validated_data, vendor_id=product.vendor_id)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        if "nickname" in self.initial_data:
            office_product = m.OfficeProduct.objects.filter(office=instance.office, product_id=instance.product_id)
            office_product.nickname = self.initial_data["nickname"]
            m.OfficeProduct.objects.bulk_update(office_product, ["nickname"])

        # if "image_url" in self.initial_data:
        #     office_product = m.OfficeProduct.objects.filter(
        #         office=instance.office, product_id=instance.product_id
        #     )
        #     office_product.image_url = self.initial_data['image_url']
        #     m.OfficeProduct.objects.bulk_update(office_product, ["image_url"])

        children_product_ids = [child.id for child in instance.product.children.all()]
        if children_product_ids:
            office_products = m.OfficeProduct.objects.filter(
                office=instance.office, product_id__in=children_product_ids
            )

            # TODO: code optimization
            if "is_favorite" in validated_data:
                for office_product in office_products:
                    office_product.is_favorite = validated_data["is_favorite"]
                m.OfficeProduct.objects.bulk_update(office_products, ["is_favorite"])

            if "is_inventory" in validated_data:
                for office_product in office_products:
                    office_product.is_favorite = validated_data["is_inventory"]
                m.OfficeProduct.objects.bulk_update(office_products, ["is_inventory"])

        return instance

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["office_product_category"] = OfficeProductCategorySerializer(instance.office_product_category).data
        ret["product"] = ProductV2Serializer(
            instance.product.parent if instance.product.parent else instance.product, context=self.context
        ).data

        if ret["is_inventory"]:
            if ret["product"]["vendor"]:
                ret["last_order_vendor"] = ret["product"]["vendor"]["id"]
            else:
                last_order_products = sorted(
                    [
                        (child["last_order_date"], child["last_order_price"], child["vendor"]["id"], child["id"])
                        for child in ret["product"]["children"]
                        if child["is_inventory"]
                    ],
                    key=lambda x: x[0],
                    reverse=True,
                )
                if last_order_products:
                    ret["last_order_date"] = last_order_products[0][0]
                    ret["last_order_price"] = last_order_products[0][1]
                    ret["last_order_vendor"] = last_order_products[0][2]
                    # this is a little complicated
                    ret["product"]["id"] = last_order_products[0][3]
                else:
                    ret["last_order_date"] = None
                    ret["last_order_price"] = None
                    ret["last_order_vendor"] = None

            # children_products = ret["product"].get("children", [])
        # if children_products:
        #     children_product_ids = [child["id"] for child in children_products]
        #     q = Q(office=instance.office) & Q(product_id__in=children_product_ids)
        #     if self.context.get("filter_inventory", False):
        #         q &= Q(is_inventory=True)
        #
        #     office_products = m.OfficeProduct.objects.filter(q)
        #     office_products = {office_product.product.id: office_product for office_product in office_products}
        #     ret["product"]["children"] = [
        #         {
        #             "product": child_product,
        #             "price": office_products[child_product["id"]].price,
        #         }
        #         for child_product in children_products
        #         if child_product["id"] in office_products
        #     ]

        # if ret["is_inventory"]:
        #     last_order = (
        #         m.VendorOrderProduct.objects.select_related("vendor_order")
        #         .filter(product__product_id=ret["product"]["product_id"])
        #         .order_by("-vendor_order__order_date")
        #         .first()
        #     )
        #     if last_order:
        #         ret["last_order_date"] = last_order.vendor_order.order_date.isoformat()
        #         ret["last_order_price"] = last_order.unit_price
        #     else:
        #         ret["last_order_date"] = None
        #         ret["last_order_price"] = None
        return ret


class ClearCartSerializer(serializers.Serializer):
    remove = serializers.ChoiceField(choices=["save_for_later", "cart"])


class ProductSuggestionSerializer(serializers.Serializer):
    id = serializers.CharField()
    product_id = serializers.CharField()
    name = serializers.CharField()
    image = serializers.CharField()
    is_inventory = serializers.BooleanField()


class RejectProductSerializer(serializers.Serializer):
    order_product_id = serializers.CharField()
    rejected_reason = serializers.ChoiceField(choices=m.VendorOrderProduct.RejectReason.choices)


class ApproveRejectSerializer(serializers.Serializer):
    is_approved = serializers.BooleanField()
    rejected_items = serializers.ListSerializer(child=RejectProductSerializer(), required=False)
    rejected_reason = serializers.CharField(required=False)


class OrderApprovalSerializer(serializers.Serializer):
    rejected_items = serializers.ListSerializer(child=RejectProductSerializer(), required=False)
    rejected_reason = serializers.CharField(required=False)


class VendorProductSearchPagination(serializers.Serializer):
    vendor = serializers.CharField()
    page = serializers.IntegerField()


class VendorProductSearchSerializer(serializers.Serializer):
    q = serializers.CharField()
    max_price = serializers.IntegerField(allow_null=True, min_value=0)
    min_price = serializers.IntegerField(allow_null=True, min_value=0)
    vendors = VendorProductSearchPagination(many=True)


class ProductPriceRequestSerializer(serializers.Serializer):
    products = serializers.ListField(child=serializers.IntegerField())


class VendorOrderReturnSerializer(serializers.Serializer):
    return_items = serializers.ListSerializer(child=serializers.CharField())
    email_list = serializers.ListSerializer(child=serializers.CharField(), required=False)


class OrderAddItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=m.Product.objects.all(),
    )
    quantity = serializers.IntegerField()


class ProcedureSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Procedure
        fields = "__all__"


class ProcedureCategoryLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ProcedureCategoryLink
        fields = ("linked_slugs", "category_order", "is_favorite")

    def update(self, instance, validated_data):
        if "category_prev_order" in self.initial_data:
            prev_pos = self.initial_data["category_prev_order"]
            new_pos = validated_data["category_order"]
            items = []

            if prev_pos > new_pos:
                items = m.ProcedureCategoryLink.objects.filter(
                    category_order__gte=new_pos, category_order__lt=prev_pos
                ).order_by("category_order")
                items = items if items else []
                for item in items:
                    item.category_order = item.category_order + 1
            elif prev_pos < new_pos:
                items = m.ProcedureCategoryLink.objects.filter(
                    category_order__gt=prev_pos, category_order__lte=new_pos
                ).order_by("category_order")
                items = items if items else []
                for item in items:
                    item.category_order = item.category_order - 1

            if items:
                m.ProcedureCategoryLink.objects.bulk_update(items, ["category_order"])

        instance = super().update(instance, validated_data)
        return instance


class ProductManagementSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=m.Product.objects.all(),
    )
    new_parent = serializers.PrimaryKeyRelatedField(queryset=m.Product.objects.all(), required=False)

    def validate_product(self, value):
        if value.parent_id is None:
            raise ValidationError("Product is orphan", code="product-is-orphan")
        return value

    def validate(self, attrs):
        new_parent = attrs.get("new_parent")
        product = attrs["product"]
        if new_parent:
            if new_parent.parent_id is not None:
                raise ValidationError("New parent cannot be child item", code="new-parent-can-not-be-child")
            if new_parent.id == product.parent_id:
                raise ValidationError("Moving to same parent has no effect", code="parent-is-same")
        return attrs


class ManualCreateProductSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=m.Product.objects.all(), required=False)
    order = serializers.PrimaryKeyRelatedField(queryset=m.Order.objects.all())
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    quantity = serializers.IntegerField()
    status = serializers.ChoiceField(choices=m.ProductStatus.choices, default=m.ProductStatus.SHIPPED)
    product_name = serializers.CharField(max_length=512, required=False)
    budget_spend_type = serializers.CharField(max_length=100)

    def create(self, validated_data):
        product = validated_data.pop("product", None)
        product_name = validated_data.pop("product_name", "")
        order = validated_data.pop("order")

        if not product:
            product = m.Product.objects.create(name=product_name, is_manual=True)
        vendor_order = m.VendorOrder.objects.filter(order=order).first()

        vendor_order.total_items += 1
        vendor_order.total_amount += validated_data["quantity"] * validated_data["unit_price"]
        vendor_order.save()

        OrderHelper.update_vendor_order_totals(vendor_order, vendor_order.total_amount)
        return m.VendorOrderProduct.objects.create(vendor_order=vendor_order, product=product, **validated_data)


class ManualOrderCreateSerializer(serializers.Serializer):
    vendor_order_id = serializers.CharField(max_length=100)
    vendor = serializers.PrimaryKeyRelatedField(queryset=m.Vendor.objects.all(), required=False)
    nickname = serializers.CharField(max_length=128, allow_null=True)
    vendor_name = serializers.CharField(max_length=100, required=False)
    order_date = serializers.DateField()
    order_status = serializers.ChoiceField(choices=m.OrderStatus.choices, default=m.OrderStatus.CLOSED)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_items = serializers.IntegerField(default=0)

    def create(self, validated_data):
        vendor_order_id = validated_data.pop("vendor_order_id")
        vendor = validated_data.pop("vendor", None)
        nickname = validated_data.pop("nickname")
        vendor_name = validated_data.pop("vendor_name", "")
        order_status = validated_data.pop("order_status")

        if not vendor:
            vendor = m.Vendor.objects.create(
                name=vendor_name, slug=vendor_name.lower().replace(" ", "_"), is_manual=True
            )
        order = m.Order.objects.create(
            office_id=self.context["office_id"], created_by=self.context["request"].user, **validated_data,
            status=order_status
        )

        return m.VendorOrder.objects.create(
            order=order,
            currency="USD",
            vendor_order_id=vendor_order_id,
            vendor=vendor,
            nickname=nickname,
            status=order_status,
            **validated_data,
        )


class SetDentalAPISerializer(serializers.Serializer):
    dental_key = serializers.SlugRelatedField(queryset=OpenDentalKey.objects.all(), slug_field="key")
    budget_type = serializers.ChoiceField(choices=BasisType.choices)


class DateRangeQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate(self, attrs):
        if ("start_date" not in attrs) or ("end_date" not in attrs):
            return {}
        start_date = attrs["start_date"]
        end_date = attrs["end_date"]
        if start_date > end_date:
            raise ValidationError("Start date cannot be more than end date")
        return attrs
