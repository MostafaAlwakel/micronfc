import json
from flask import render_template, request, redirect, url_for, flash, abort, jsonify, session
from flask_login import login_required, current_user
from . import store_bp
from .models import Product, Order, CartOrder
from .stripe_utils import create_checkout_session, create_cart_checkout_session, verify_webhook
from models import db


def _get_cart():
    return session.get('cart', {})


def _cart_count():
    return sum(_get_cart().values())


def _get_cart_items():
    cart = _get_cart()
    items = []
    total = 0.0
    for pid_str, qty in cart.items():
        product = Product.query.get(int(pid_str))
        if product and product.is_active:
            subtotal = product.price * qty
            total += subtotal
            items.append({'product': product, 'quantity': qty, 'subtotal': subtotal})
    return items, total


@store_bp.route('/')
def index():
    products = Product.query.filter_by(is_active=True).all()
    return render_template('store/index.html', products=products, cart_count=_cart_count())


@store_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_active:
        abort(404)
    return render_template('store/product.html', product=product, cart_count=_cart_count())


@store_bp.route('/cart/add/<int:product_id>', methods=['POST'])
def cart_add(product_id):
    if not current_user.is_authenticated:
        session['redirect_after_login'] = url_for('store.checkout', product_id=product_id)
        session.modified = True
        return redirect(url_for('login'))
    product = Product.query.get_or_404(product_id)
    if not product.is_active or product.stock < 1:
        flash('Product not available.', 'danger')
        return redirect(request.referrer or url_for('store.index'))
    quantity = int(request.form.get('quantity', 1))
    cart = session.get('cart', {})
    pid_str = str(product_id)
    cart[pid_str] = min(cart.get(pid_str, 0) + quantity, product.stock)
    session['cart'] = cart
    session.modified = True
    flash(f'"{product.name}" added to cart!', 'success')
    return redirect(request.referrer or url_for('store.index'))


@store_bp.route('/cart')
def cart():
    items, total = _get_cart_items()
    return render_template('store/cart.html', items=items, total=total, cart_count=_cart_count())


@store_bp.route('/cart/remove/<int:product_id>', methods=['POST'])
def cart_remove(product_id):
    cart = session.get('cart', {})
    cart.pop(str(product_id), None)
    session['cart'] = cart
    session.modified = True
    return redirect(url_for('store.cart'))


@store_bp.route('/cart/update/<int:product_id>', methods=['POST'])
def cart_update(product_id):
    product = Product.query.get_or_404(product_id)
    qty = int(request.form.get('quantity', 1))
    cart = session.get('cart', {})
    pid_str = str(product_id)
    if qty < 1:
        cart.pop(pid_str, None)
    else:
        cart[pid_str] = min(qty, product.stock)
    session['cart'] = cart
    session.modified = True
    return redirect(url_for('store.cart'))


@store_bp.route('/cart/checkout', methods=['GET', 'POST'])
def cart_checkout():
    if not current_user.is_authenticated:
        session['redirect_after_login'] = url_for('store.cart_checkout')
        session.modified = True
        return redirect(url_for('login'))
    items, total = _get_cart_items()
    if not items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('store.cart'))

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        payment_method = request.form.get('payment_method', 'card')

        if not phone or not address:
            flash('Phone number and address are required.', 'error')
            return render_template('store/checkout.html', cart_items=items, cart_total=total,
                                   cart_count=_cart_count())

        items_json = json.dumps([
            {'product_id': i['product'].id, 'name': i['product'].name,
             'quantity': i['quantity'], 'price': i['product'].price}
            for i in items
        ])
        cart_order = CartOrder(
            customer_name=current_user.name, customer_email=current_user.email,
            customer_phone=phone, customer_address=address, items=items_json,
            total_price=total, payment_method=payment_method, status='pending'
        )
        db.session.add(cart_order)
        db.session.commit()

        if payment_method == 'cash':
            cart_order.status = 'cash_on_delivery'
            db.session.commit()
            session.pop('cart', None)
            return redirect(url_for('store.success', order_id=cart_order.id, type='cart'))

        try:
            stripe_session = create_cart_checkout_session(items, cart_order.id)
            cart_order.stripe_session_id = stripe_session.id
            db.session.commit()
            session.pop('cart', None)
            return redirect(stripe_session.url, code=303)
        except Exception as e:
            print('Stripe error:', e)
            db.session.delete(cart_order)
            db.session.commit()
            flash('Payment setup failed. Please try again.', 'danger')
            return redirect(url_for('store.cart_checkout'))

    return render_template('store/checkout.html', cart_items=items, cart_total=total,
                           cart_count=_cart_count())


@store_bp.route('/checkout/<int:product_id>', methods=['GET', 'POST'])
def checkout(product_id):
    if not current_user.is_authenticated:
        session['redirect_after_login'] = url_for('store.checkout', product_id=product_id)
        session.modified = True
        return redirect(url_for('login'))
    product = Product.query.get_or_404(product_id)
    if not product.is_active or product.stock < 1:
        flash('This product is not available.', 'danger')
        return redirect(url_for('store.index'))

    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        quantity = int(request.form.get('quantity', 1))
        payment_method = request.form.get('payment_method', 'card')

        if not phone or not address:
            flash('Phone number and address are required.', 'error')
            return render_template('store/checkout.html', product=product, cart_count=_cart_count())

        if quantity < 1 or quantity > product.stock:
            flash('Invalid quantity.', 'danger')
            return redirect(url_for('store.checkout', product_id=product_id))

        order = Order(
            product_id=product.id,
            customer_name=current_user.name,
            customer_email=current_user.email,
            customer_phone=phone,
            customer_address=address,
            quantity=quantity,
            total_price=product.price * quantity,
            status='pending',
            payment_method=payment_method,
            tracking_number=Order.generate_tracking(),
            user_id=current_user.id
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

    return render_template('store/checkout.html', product=product, cart_count=_cart_count())


@store_bp.route('/success')
def success():
    order_id = request.args.get('order_id')
    order_type = request.args.get('type', 'single')
    if order_type == 'cart':
        cart_order = CartOrder.query.get(int(order_id)) if order_id else None
        return render_template('store/success.html', cart_order=cart_order)
    order = Order.query.get(int(order_id)) if order_id else None
    return render_template('store/success.html', order=order)


@store_bp.route('/cancel')
def cancel():
    order_id = request.args.get('order_id')
    order_type = request.args.get('type', 'single')
    if order_type == 'cart':
        cart_order = CartOrder.query.get(int(order_id)) if order_id else None
        if cart_order and cart_order.status == 'pending':
            cart_order.status = 'cancelled'
            db.session.commit()
        return render_template('store/cancel.html', cart_order=cart_order)
    order = Order.query.get(int(order_id)) if order_id else None
    if order and order.status == 'pending':
        order.status = 'cancelled'
        db.session.commit()
    return render_template('store/cancel.html', order=order)


@store_bp.route('/track')
@store_bp.route('/track/<tracking_number>')
@login_required
def track_order(tracking_number=None):
    # Accept tracking number from URL segment or GET query param
    tn = tracking_number or request.args.get('tracking_number', '').strip()
    # Redirect form submissions to clean URL
    if tn and not tracking_number:
        return redirect(url_for('store.track_order', tracking_number=tn))
    order = None
    error = None
    if tn:
        order = Order.query.filter_by(tracking_number=tn).first()
        if order:
            if order.user_id is not None and order.user_id != current_user.id:
                # Order belongs to a different user
                order = None
                error = "Order not found or doesn't belong to your account."
            elif order.user_id is None:
                # Backfill: link old order to the user who has the tracking number
                order.user_id = current_user.id
                db.session.commit()
        else:
            error = "No order found with that tracking number."
    return render_template('store/track.html', order=order, tracking_number=tn, error=error)


@store_bp.route('/my-orders')
@login_required
def my_orders():
    from datetime import datetime as _dt

    # ── Single-product orders (Order) ──────────────────────────────────────
    single = Order.query.filter(
        db.or_(
            Order.user_id == current_user.id,
            Order.customer_email == current_user.email
        )
    ).order_by(Order.created_at.desc()).all()

    needs_save = False
    for o in single:
        if o.user_id is None:
            o.user_id = current_user.id
            needs_save = True
        o._is_cart    = False
        o._items_desc = (o.product.name if o.product else '—') + f' × {o.quantity}'
        o._tracking   = o.tracking_number or ''
    if needs_save:
        db.session.commit()

    # ── Cart orders (CartOrder) ─────────────────────────────────────────────
    cart = CartOrder.query.filter_by(
        customer_email=current_user.email
    ).order_by(CartOrder.created_at.desc()).all()

    for co in cart:
        co._is_cart    = True
        items          = co.get_items()
        co._items_desc = (', '.join(f"{i['name']} × {i['quantity']}" for i in items)
                          if items else '—')
        co._tracking   = ''

    # ── Merge and sort by date ──────────────────────────────────────────────
    all_orders = sorted(
        list(single) + list(cart),
        key=lambda x: x.created_at or _dt(2000, 1, 1),
        reverse=True
    )

    return render_template('store/my_orders.html', orders=all_orders)


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
        metadata = session_obj.get('metadata', {})

        order_id = metadata.get('order_id')
        if order_id:
            order = Order.query.get(int(order_id))
            if order:
                order.status = 'paid'
                product = Product.query.get(order.product_id)
                if product and product.stock >= order.quantity:
                    product.stock -= order.quantity
                db.session.commit()

        cart_order_id = metadata.get('cart_order_id')
        if cart_order_id:
            cart_order = CartOrder.query.get(int(cart_order_id))
            if cart_order:
                cart_order.status = 'paid'
                for item in cart_order.get_items():
                    product = Product.query.get(item['product_id'])
                    if product and product.stock >= item['quantity']:
                        product.stock -= item['quantity']
                db.session.commit()

    return jsonify({'status': 'ok'})
