# from celery.result import AsyncResult
import decimal
import logging
from collections import Counter
from decimal import Decimal
from typing import List, NamedTuple

import slugify
from creditcards.validators import CCNumberValidator, CSCValidator, ExpiryDateValidator
from django.db import transaction
from django.utils import timezone
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.accounts.services.stripe import (
    add_customer_to_stripe,
    create_subscription,
    get_payment_method_token,
)
from apps.common.serializers import Base64ImageField, OptionalSchemeURLValidator

from ..common.month import Month
from . import models as m
from .models import BUILTIN_BUDGET_SLUGS, Subaccount

# from .tasks import fetch_orders_from_vendor
from .tasks import send_welcome_email

logger = logging.getLogger(__name__)


class VendorLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Vendor
        fields = "__all__"


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Vendor
        fields = "__all__"


class OpenDentalKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = m.OpenDentalKey
        fields = "__all__"


class BaseValues(NamedTuple):
    adjusted_production: decimal.Decimal
    collection: decimal.Decimal


class SubaccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Subaccount
        fields = ["id", "slug", "percentage", "spend", "name", "vendors"]


class SubaccountStatsSerializer(serializers.ModelSerializer):
    ytd = serializers.DictField()

    class Meta:
        model = m.Subaccount
        fields = ["id", "slug", "percentage", "spend", "name", "vendors", "ytd"]


class SubaccountSubmitSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()

    class Meta:
        model = m.Subaccount
        fields = ["id", "slug", "percentage", "name", "vendors"]
        extra_kwargs = {"slug": {"required": False}, "vendors": {"required": False, "allow_empty": True}}


class SubaccountCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Subaccount
        fields = ["slug", "percentage", "vendors", "name"]
        extra_kwargs = {"slug": {"required": False}, "vendors": {"allow_empty": True}}

    def validate(self, attrs):
        slug = attrs.get("slug")
        vendors = attrs.get("vendors", [])
        if slug and vendors:
            raise ValidationError("Vendors cannot be specified for default budget categories")
        return attrs

    def create(self, attrs):
        attrs["budget"] = self.context["budget"]
        if "slug" not in attrs:
            attrs["slug"] = slugify.slugify(attrs["name"])
        return super().create(attrs)


class SubaccountUpdateSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = m.Subaccount
        fields = ["id", "percentage", "name", "vendors"]


class SubaccountRemoveSerializer(serializers.Serializer):
    # The choices will be set up in constructor
    substitute_slug = serializers.ChoiceField(choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subaccount: Subaccount = self.context["subaccount"]
        possible_slugs = set(
            Subaccount.objects.filter(budget__office_id=subaccount.budget.office_id)
            .values_list("slug", flat=True)
            .distinct()
        ) - {subaccount.slug}
        self.fields["substitute_slug"].choices = possible_slugs


class BudgetSerializer(serializers.ModelSerializer):
    subaccounts = SubaccountSerializer(many=True)

    class Meta:
        model = m.Budget
        fields = "__all__"


class BudgetStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Budget
        fields = "__all__"


class BudgetChartSerializer(serializers.ModelSerializer):
    subaccounts = SubaccountSerializer(many=True)

    class Meta:
        model = m.Budget
        fields = ["month", "subaccounts"]


class BudgetUpdateSerializer(serializers.ModelSerializer):
    on_boarding_step = serializers.IntegerField(required=False)
    subaccounts = SubaccountSubmitSerializer(many=True)

    class Meta:
        model = m.Budget
        fields = ["on_boarding_step", "basis", "adjusted_production", "collection", "subaccounts"]

    def create_subaccounts(self, subaccounts):
        s = SubaccountCreateSerializer(data=subaccounts, many=True, context={"budget": self.instance})
        s.is_valid(raise_exception=True)
        s.save()

    def update_and_remove_subaccounts(self, data):
        subaccounts = self.instance.subaccounts.all()
        data_objs = {s["id"]: s for s in data}
        db_objs = {s.id: s for s in subaccounts}
        extra_data_ids = data_objs.keys() - db_objs.keys()
        if extra_data_ids:
            raise ValidationError(f"These subaccounts do not belong to budget: {extra_data_ids}")

        for sdata in data:
            subaccount = db_objs[sdata["id"]]
            if "vendors" in sdata:
                if sdata["vendors"] and subaccount.slug in BUILTIN_BUDGET_SLUGS:
                    raise ValidationError("Vendors are not allowed for standard budget")

            for field_name in ("name", "percentage", "vendors"):
                if field_name in sdata:
                    setattr(subaccount, field_name, sdata[field_name])
            subaccount.save()

    def update(self, instance: m.Budget, attrs):
        subaccounts = attrs.pop("subaccounts", [])
        on_boarding_step = attrs.pop("on_boarding_step", None)

        if on_boarding_step is not None:
            m.Company.objects.filter(pk=instance.office.company_id).update(on_boarding_step=on_boarding_step)
        db_subaccounts = {s.id: s for s in instance.subaccounts.all()}
        vendors = []
        for sdata in subaccounts:
            if "vendors" in sdata:
                vendors.extend(sdata["vendors"])
            elif "id" in sdata:
                subaccount_id = sdata["id"]
                if subaccount_id not in db_subaccounts:
                    continue
                vendors.extend(db_subaccounts[subaccount_id].vendors)
        counter = Counter(vendors)
        duplicate_vendors = [k for k, v in counter.items() if v > 1]
        if duplicate_vendors:
            raise ValidationError(f"The following vendors were passed more than once: {duplicate_vendors}")
        if subaccounts:
            self.update_and_remove_subaccounts([s for s in subaccounts if "id" in s])
            self.create_subaccounts([s for s in subaccounts if "id" not in s])
        instance = super().update(instance, attrs)
        return instance


class BudgetCreateSerializer(serializers.ModelSerializer):
    subaccounts = SubaccountCreateSerializer(many=True)

    class Meta:
        model = m.Budget
        fields = ["basis", "adjusted_production", "collection", "subaccounts"]

    def create(self, attrs):
        subaccounts = attrs.pop("subaccounts")
        office_id = self.context.get("office_pk")
        with transaction.atomic():
            instance = super().create(
                {**attrs, "office_id": office_id, "month": Month.from_date(timezone.localdate())}
            )
            for subaccount_data in subaccounts:
                ss = SubaccountCreateSerializer(data=subaccount_data, context={**self.context, "budget": instance})
                ss.is_valid(raise_exception=True)
                ss.create(subaccount_data)
                # TODO: write not found logic and wrap into transaction
            return instance


class OfficeBudgetSerializer(serializers.ModelSerializer):
    office = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all(), required=False)
    # spend = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    remaining_budget = serializers.SerializerMethodField()

    class Meta:
        model = m.OfficeBudget
        exclude = ("created_at", "updated_at")

    def get_remaining_budget(self, instance):
        TWO_DECIMAL_PLACES = Decimal(10) ** -2
        return {
            "dental": (instance.dental_budget - instance.dental_spend).quantize(TWO_DECIMAL_PLACES),
            "office": (instance.office_budget - instance.office_spend).quantize(TWO_DECIMAL_PLACES),
        }


class OfficeBudgetChartSerializer(serializers.Serializer):
    month = serializers.CharField()
    dental_budget = serializers.DecimalField(max_digits=8, decimal_places=2)
    dental_spend = serializers.DecimalField(max_digits=8, decimal_places=2)
    office_budget = serializers.DecimalField(max_digits=8, decimal_places=2)
    office_spend = serializers.DecimalField(max_digits=8, decimal_places=2)


class OfficeAddressSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = m.OfficeAddress
        exclude = ("office",)


class OfficeSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.OfficeSetting
        exclude = ("office",)


class AddressEditorMixin:
    def _create_or_update_addresses(self, office: m.Office, addresses: List[dict]):
        for address in addresses:
            address_id = address.pop("id", [])
            if address_id:
                office_address = m.OfficeAddress.objects.get(id=address_id)
                for key, value in address.items():
                    if not hasattr(office_address, key):
                        continue
                    setattr(office_address, key, value)
                office_address.save()
            else:
                m.OfficeAddress.objects.create(office=office, **address)


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Region
        fields = "__all__"


class OfficeSerializer(serializers.ModelSerializer, AddressEditorMixin):
    id = serializers.IntegerField(required=False)
    company = serializers.PrimaryKeyRelatedField(queryset=m.Company.objects.all(), required=False)
    addresses = OfficeAddressSerializer(many=True, required=False)
    logo = Base64ImageField(required=False)
    vendors = VendorLiteSerializer(many=True, required=False)
    region = RegionSerializer()
    phone_number = PhoneNumberField()
    website = serializers.CharField(validators=[OptionalSchemeURLValidator()], allow_null=True)
    cc_number = serializers.CharField(validators=[CCNumberValidator()], write_only=True)
    cc_expiry = serializers.DateField(
        validators=[ExpiryDateValidator()], input_formats=["%m/%y"], format="%m/%y", write_only=True
    )
    coupon = serializers.CharField(write_only=True, required=False)
    cc_code = serializers.CharField(validators=[CSCValidator()], write_only=True)
    settings = OfficeSettingSerializer(read_only=True)
    name = serializers.CharField()
    dental_api = OpenDentalKeySerializer()
    practice_software = serializers.CharField()
    budget = BudgetSerializer()

    class Meta:
        model = m.Office
        fields = "__all__"

    def to_representation(self, instance):
        res = super().to_representation(instance)
        if self.context.get("exclude_vendors"):
            res.pop("vendors")
        return res

    def update(self, instance, validated_data):
        if "addresses" in validated_data:
            addresses = validated_data.pop("addresses")
            self._create_or_update_addresses(self.instance, addresses)
        return super().update(instance, validated_data)


class BaseCompanyMemberSerializer(serializers.ModelSerializer):
    company = serializers.PrimaryKeyRelatedField(queryset=m.Company.objects.all(), allow_null=True)

    class Meta:
        model = m.CompanyMember
        exclude = ("token",)


class BaseCompanyMemberReadSerializer(BaseCompanyMemberSerializer):
    role_name = serializers.CharField(source="get_role_display", required=False)


class CompanyMemberSerializer(BaseCompanyMemberReadSerializer):
    office = OfficeSerializer()


class CompanyMemberUpdateSerializer(BaseCompanyMemberSerializer):
    def validate(self, attrs):
        company = attrs["company"]
        office = attrs["office"]
        if office.company_id != company.id:
            raise ValidationError("Office must belong to company")
        return attrs


class BaseCompanySerializer(serializers.ModelSerializer, AddressEditorMixin):
    class Meta:
        model = m.Company
        fields = "__all__"

    def _update_subscription(self, offices, offices_data, company=None):
        try:
            for office, office_data in zip(offices, offices_data):
                card_number = office_data.get("cc_number", None)
                expiry = office_data.get("cc_expiry", None)
                cvc = office_data.get("cc_code", None)
                coupon = office_data.get("coupon", None)

                if card_number or expiry or cvc:
                    card_token = get_payment_method_token(card_number=card_number, expiry=expiry, cvc=cvc)
                    if office.cards.filter(card_token=card_token.id).exists():
                        continue

                    _, customer = add_customer_to_stripe(
                        email=self.context["request"].user.email,
                        customer_name=office.name,
                        payment_method_token=card_token,
                    )

                    subscription = create_subscription(customer_id=customer.id, promocode=coupon)

                    with transaction.atomic():
                        m.Card.objects.create(
                            last4=card_token.card.last4,
                            customer_id=customer.id,
                            card_token=card_token.id,
                            office=office,
                        )
                        m.Subscription.objects.create(
                            subscription_id=subscription.id, office=office, start_on=timezone.localtime().date()
                        )
                else:
                    # Check if the company has a previous subscription
                    company_offices = m.Office.objects.filter(company_id=company.id).values("id")
                    offices_ids = [office["id"] for office in company_offices]
                    subscription = m.Subscription.objects.filter(office_id__in=offices_ids, cancelled_on__isnull=True)
                    if subscription:
                        # Add office with the previous subscription
                        m.Subscription.objects.create(office=offices[0], start_on=timezone.localtime().date())

        except Exception as e:
            msg = str(e)
            if "No such coupon" in msg:
                # NOTE: This is temporary fix.
                # Need to update this later using the custom serializer or whatever..
                msg = "Invalid Coupon Code"
            raise serializers.ValidationError({"message": msg})

    def _create_or_update_office(self, company, **kwargs):
        office_id = kwargs.pop("id", None)
        addresses = kwargs.pop("addresses", [])
        if office_id:
            office = m.Office.objects.get(id=office_id, company=company)
            for key, value in kwargs.items():
                if not hasattr(office, key):
                    continue
                setattr(office, key, value)
            office.save()
        else:
            office = m.Office.objects.create(
                company=company,
                region=kwargs.get("region"),
                name=kwargs["name"],
                phone_number=kwargs.get("phone_number"),
                website=kwargs.get("website"),
                practice_software=kwargs.get("practice_software"),
                sub_company_id=kwargs.get("sub_company"),
            )
            m.OfficeSetting.objects.create(office=office)

            request = self.context.get("request")
            if request and hasattr(request, "user"):
                user = request.user
                m.CompanyMember.objects.filter(company_id=company.id, user_id=user.id, office_id__isnull=True).update(
                    office_id=office.id
                )
        self._create_or_update_addresses(office, addresses)
        return office

    def create(self, validated_data):
        offices_data = validated_data.pop("offices", None)
        offices = []
        with transaction.atomic():
            company = m.Company.objects.create(**validated_data)
            for office in offices_data:
                offices.append(self._create_or_update_office(company, **office))

            m.Office.objects.bulk_create(offices)

        self._update_subscription(offices, offices_data)
        return company

    def update(self, instance, validated_data):
        offices_data = validated_data.pop("offices", [])
        offices = []
        with transaction.atomic():
            for key, value in validated_data.items():
                if key == "on_boarding_step" and instance.on_boarding_step > value:
                    continue
                setattr(instance, key, value)

            for office in offices_data:
                offices.append(self._create_or_update_office(instance, **office))

            self._update_subscription(offices, offices_data, instance)

            if validated_data:
                instance.save()

        # TODO: pretty hacky way to detect if we are in onboarding
        #       perfectly maybe we should have separate handler
        #       for onboarding stuff
        if "on_boarding_step" in validated_data and validated_data["on_boarding_step"] == 2:
            user = self.context["request"].user
            send_welcome_email.delay(user_id=user.id)

        return instance

    def to_representation(self, instance):
        res = super().to_representation(instance)
        if self.context.get("exclude_offices"):
            res.pop("offices")
        return res


class CompanySerializer(BaseCompanySerializer):
    offices = OfficeSerializer(many=True)


class UserSignupSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField()
    company_name = serializers.CharField()
    token = serializers.CharField(required=False)


class CompanyMemberInviteSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=(m.User.Role.ADMIN, m.User.Role.USER, m.User.Role.MID_ADMIN))
    offices = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all(), required=False),
        required=False,
        allow_null=True,
    )
    email = serializers.EmailField()


class CompanyMemberBulkInviteSerializer(serializers.Serializer):
    on_boarding_step = serializers.IntegerField(required=False)
    members = serializers.ListField(child=CompanyMemberInviteSerializer(), allow_empty=False)


class ShippingMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ShippingMethod
        fields = "__all__"


class OfficeVendorSerializer(serializers.ModelSerializer):
    office = serializers.PrimaryKeyRelatedField(queryset=m.Office.objects.all(), allow_null=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = m.OfficeVendor
        fields = "__all__"
        extra_kwargs = {"shipping_options": {"read_only": True}}


class OfficeVendorListSerializer(serializers.ModelSerializer):
    vendor = VendorLiteSerializer()
    default_shipping_option = ShippingMethodSerializer(read_only=True)
    shipping_options = ShippingMethodSerializer(many=True, read_only=True)

    class Meta:
        model = m.OfficeVendor
        exclude = (
            "office",
            "password",
        )


class UserSerializer(serializers.ModelSerializer):
    company = serializers.SerializerMethodField()
    avatar = Base64ImageField()

    class Meta:
        model = m.User
        exclude = (
            "password",
            "is_staff",
            "groups",
            "user_permissions",
        )

    def get_company(self, instance):
        company = m.Company.objects.filter(members__user=instance).first()
        if company:
            return CompanySerializer(company, context=self.context).data


class VendorRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.VendorRequest
        fields = ("id", "company", "vendor_name", "description")
        extra_kwargs = {"company": {"write_only": True}}


class CouponCheckQuerySerializer(serializers.Serializer):
    code = serializers.CharField()


class OnboardingStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.OnboardingStatus
        fields = "__all__"
        read_only_fields = ["company"]


class SubCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = m.SubCompany
        fields = "__all__"

    def create(self, validated_data):
        validated_data["is_active"] = True
        sub_company = super().create(validated_data)
        return sub_company

    def update(self, instance, validated_data):
        validated_data["is_active"] = True
        return super().update(instance, validated_data)
