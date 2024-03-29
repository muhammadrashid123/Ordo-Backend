import datetime
from typing import Optional

import stripe
import stripe.error
from django.conf import settings

stripe.api_key = settings.STRIPE_API_KEY


def add_customer_to_stripe(
    email: str,
    customer_name: str,
    card_number: Optional[str] = None,
    expiry: Optional[datetime.date] = None,
    cvc: Optional[str] = None,
    payment_method_token: Optional[stripe.Token] = None,
):
    """
    Registers user in Stripe and saves card token and customer id in user's account
    """
    # account = office.accounts.first()
    # if not account:
    #     account = Account.objects.create(office=office)
    #
    if payment_method_token is None:
        payment_method_token = get_payment_method_token(card_number, expiry, cvc)

    customer = register_customer(email, customer_name, payment_method_token)
    return payment_method_token, customer


def get_payment_method_token(card_number: str, expiry: datetime.date, cvc: str) -> stripe.Token:
    """
    Registers card in Stripe and returns its token
    """
    payment_token = stripe.Token.create(
        card={
            "number": card_number,
            "exp_month": expiry.month,
            "exp_year": expiry.year,
            "cvc": cvc,
        }
    )
    return payment_token


def register_customer(email: str, name: str, token: stripe.Token) -> stripe.Customer:
    """
    Registers user as customer in Stripe
    """
    return stripe.Customer.create(
        email=email,
        name=name,
        source=token.id,
    )


def create_subscription(customer_id, promocode: Optional[str] = None):
    """
    Adds a subscription to given plan with promocode applied in Stripe
    """
    params = {
        "customer": customer_id,
        "trial_period_days": 14,
        "items": [{"price": settings.STRIPE_SUBSCRIPTION_PRICE_ID}],
    }
    if promocode:
        params["coupon"] = promocode
    return stripe.Subscription.create(**params)


def cancel_subscription(subscription_id):
    return stripe.Subscription.delete(subscription_id)


def get_coupon_data(coupon_code):
    try:
        coupon = stripe.Coupon.retrieve(coupon_code)
    except stripe.error.InvalidRequestError:
        return None
    return coupon
