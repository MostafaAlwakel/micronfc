import os
import stripe

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
DOMAIN = os.getenv('DOMAIN', 'https://www.micronfc.info')


def create_checkout_session(product, quantity, order_id):
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'egp',
                'product_data': {'name': product.name},
                'unit_amount': int(product.price * 100),
            },
            'quantity': quantity,
        }],
        mode='payment',
        success_url=f"{DOMAIN}/store/success?session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}",
        cancel_url=f"{DOMAIN}/store/cancel?order_id={order_id}",
        metadata={'order_id': str(order_id)}
    )
    return session


def verify_webhook(payload, sig_header):
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
