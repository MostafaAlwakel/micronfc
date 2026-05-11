import json
import cloudinary.uploader
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from . import store_bp
from .models import Product, Order, CartOrder, StoreStaff
from datetime import datetime as _dt
from models import db, User


def _upload_images(files):
    """Upload multiple files to Cloudinary, return list of secure URLs."""
    urls = []
    for f in files:
        if f and f.filename:
            try:
                result = cloudinary.uploader.upload(f)
                urls.append(result['secure_url'])
            except Exception as e:
                print(f"Cloudinary upload error: {e}")
    return urls


def store_admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role in ['admin', 'subadmin']:
            return f(*args, **kwargs)
        staff = StoreStaff.query.filter_by(user_id=current_user.id).first()
        if not staff:
            flash('Access denied.', 'danger')
            return redirect(url_for('store.index'))
        return f(*args, **kwargs)
    return decorated


def _annotate_order(o):
    """Attach display helpers onto a single-product Order instance."""
    o._is_cart = False
    o._product_desc = f"{(o.product.name if o.product else '—')} × {o.quantity}"
    o._tracking = o.tracking_number or ''
    return o


def _annotate_cart_order(co):
    """Attach display helpers onto a CartOrder instance."""
    co._is_cart = True
    items = co.get_items()
    co._product_desc = (', '.join(f"{i['name']} ×{i['quantity']}" for i in items)
                        if items else '—')
    co._tracking = ''
    return co


@store_bp.route('/dashboard')
@store_admin_required
def store_dashboard():
    total_products = Product.query.count()
    active_products = Product.query.filter_by(is_active=True).count()

    total_orders = Order.query.count() + CartOrder.query.count()
    paid_orders = (Order.query.filter_by(status='paid').count() +
                   CartOrder.query.filter_by(status='paid').count())
    revenue = (
        (db.session.query(db.func.sum(Order.total_price))
         .filter(Order.status == 'paid').scalar() or 0) +
        (db.session.query(db.func.sum(CartOrder.total_price))
         .filter(CartOrder.status == 'paid').scalar() or 0)
    )

    recent_single = [_annotate_order(o)
                     for o in Order.query.order_by(Order.created_at.desc()).limit(10).all()]
    recent_cart = [_annotate_cart_order(co)
                   for co in CartOrder.query.order_by(CartOrder.created_at.desc()).limit(10).all()]
    recent_orders = sorted(recent_single + recent_cart,
                           key=lambda x: x.created_at or _dt(2000, 1, 1),
                           reverse=True)[:10]

    return render_template('store/dashboard.html',
        total_products=total_products,
        active_products=active_products,
        total_orders=total_orders,
        paid_orders=paid_orders,
        revenue=revenue,
        recent_orders=recent_orders
    )


@store_bp.route('/dashboard/products')
@store_admin_required
def dashboard_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('store/products.html', products=products)


@store_bp.route('/dashboard/products/add', methods=['GET', 'POST'])
@store_admin_required
def dashboard_add_product():
    if request.method == 'POST':
        image_urls = _upload_images(request.files.getlist('images'))
        product = Product(
            name=request.form['name'].strip(),
            description=request.form.get('description', '').strip(),
            price=float(request.form['price']),
            stock=int(request.form.get('stock', 0)),
            image_url=image_urls[0] if image_urls else '',
            images=json.dumps(image_urls),
            is_active='is_active' in request.form
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added!', 'success')
        return redirect(url_for('store.dashboard_products'))
    return render_template('store/add_product.html')


@store_bp.route('/dashboard/products/edit/<int:product_id>', methods=['GET', 'POST'])
@store_admin_required
def dashboard_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form['name'].strip()
        product.description = request.form.get('description', '').strip()
        product.price = float(request.form['price'])
        product.stock = int(request.form.get('stock', 0))
        product.is_active = 'is_active' in request.form

        new_urls = _upload_images(request.files.getlist('images'))
        if new_urls:
            # New uploads replace old images
            product.images = json.dumps(new_urls)
            product.image_url = new_urls[0]
        else:
            # Keep existing images; allow manual URL override
            manual_url = request.form.get('image_url', '').strip()
            if manual_url:
                product.image_url = manual_url

        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('store.dashboard_products'))
    return render_template('store/edit_product.html', product=product)


@store_bp.route('/dashboard/products/delete/<int:product_id>', methods=['POST'])
@store_admin_required
def dashboard_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted!', 'success')
    return redirect(url_for('store.dashboard_products'))


@store_bp.route('/dashboard/orders')
@store_admin_required
def dashboard_orders():
    status = request.args.get('status', '')

    q_single = Order.query
    q_cart = CartOrder.query
    if status:
        q_single = q_single.filter_by(status=status)
        q_cart = q_cart.filter_by(status=status)

    single = [_annotate_order(o) for o in q_single.order_by(Order.created_at.desc()).all()]
    cart = [_annotate_cart_order(co) for co in q_cart.order_by(CartOrder.created_at.desc()).all()]

    orders = sorted(single + cart,
                    key=lambda x: x.created_at or _dt(2000, 1, 1),
                    reverse=True)

    return render_template('store/orders.html', orders=orders, current_status=status)


@store_bp.route('/dashboard/orders/update/<int:order_id>', methods=['POST'])
@store_admin_required
def dashboard_update_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = request.form['status']
    db.session.commit()
    flash('Order status updated!', 'success')
    return redirect(url_for('store.dashboard_orders'))


@store_bp.route('/dashboard/cart-orders/update/<int:order_id>', methods=['POST'])
@store_admin_required
def dashboard_update_cart_order(order_id):
    cart_order = CartOrder.query.get_or_404(order_id)
    cart_order.status = request.form['status']
    db.session.commit()
    flash('Order status updated!', 'success')
    return redirect(url_for('store.dashboard_orders'))


@store_bp.route('/dashboard/staff')
@store_admin_required
def dashboard_staff():
    staff_list = StoreStaff.query.all()
    return render_template('store/staff.html', staff_list=staff_list)


@store_bp.route('/dashboard/staff/add', methods=['POST'])
@store_admin_required
def dashboard_add_staff():
    email = request.form.get('email', '').strip()
    role = request.form.get('role', 'staff')
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('No user found with that email.', 'danger')
        return redirect(url_for('store.dashboard_staff'))
    if StoreStaff.query.filter_by(user_id=user.id).first():
        flash('User is already a staff member.', 'warning')
        return redirect(url_for('store.dashboard_staff'))
    db.session.add(StoreStaff(user_id=user.id, role=role))
    db.session.commit()
    flash(f'{user.name} added as store {role}.', 'success')
    return redirect(url_for('store.dashboard_staff'))


@store_bp.route('/dashboard/staff/remove/<int:staff_id>', methods=['POST'])
@store_admin_required
def dashboard_remove_staff(staff_id):
    staff = StoreStaff.query.get_or_404(staff_id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff member removed.', 'success')
    return redirect(url_for('store.dashboard_staff'))
