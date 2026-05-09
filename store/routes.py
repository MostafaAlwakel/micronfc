from flask import render_template, request, redirect, url_for, flash, abort, jsonify
from . import store_bp
from .models import Product, Order
from .stripe_utils import create_checkout_session, verify_webhook
from models import db


@store_bp.route('/')
def index():
    products = Product.query.filter_by(is_active=True).all()
    return render_template('store/index.html', products=products)


@store_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_active:
        abort(404)
    return render_template('store/product.html', product=product)


@store_bp.route('/checkout/<int:product_id>', methods=['GET', 'POST'])
def checkout(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_active or product.stock < 1:
        flash('This product is not available.', 'danger')
        return redirect(url_for('store.index'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        quantity = int(request.form.get('quantity', 1))
        payment_method = request.form.get('payment_method', 'card')

        if quantity < 1 or quantity > product.stock:
            flash('Invalid quantity.', 'danger')
            return redirect(url_for('store.checkout', product_id=product_id))

        order = Order(
            product_id=product.id,
            customer_name=name,
            customer_email=email,
            customer_phone=phone,
            customer_address=address,
            quantity=quantity,
            total_price=product.price * quantity,
            status='pending'
        )
        db.session.add(order)
        db.session.commit()

        if payment_method == 'cash':
            order.status = 'cash_on_delivery'
            db.session.commit()
            return redirect(url_for('store.success', order_id=order.id))

        try:
            stripe_session = create_checkout_session(product, quantity, order.id)
            order.stripe_session_id = stripe_session.id
            db.session.commit()
            return redirect(stripe_session.url, code=303)
        except Exception as e:
            print('Stripe error:', e)
            db.session.delete(order)
            db.session.commit()
            flash('Payment setup failed. Please try again.', 'danger')
            return redirect(url_for('store.checkout', product_id=product_id))

    return render_template('store/checkout.html', product=product)


@store_bp.route('/success')
def success():
    order_id = request.args.get('order_id')
    order = Order.query.get(int(order_id)) if order_id else None
    return render_template('store/success.html', order=order)


@store_bp.route('/cancel')
def cancel():
    order_id = request.args.get('order_id')
    order = Order.query.get(int(order_id)) if order_id else None
    if order and order.status == 'pending':
        order.status = 'cancelled'
        db.session.commit()
    return render_template('store/cancel.html', order=order)


@store_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = verify_webhook(payload, sig_header)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        order_id = session_obj.get('metadata', {}).get('order_id')
        if order_id:
            order = Order.query.get(int(order_id))
            if order:
                order.status = 'paid'
                product = Product.query.get(order.product_id)
                if product and product.stock >= order.quantity:
                    product.stock -= order.quantity
                db.session.commit()

    return jsonify({'status': 'ok'})
