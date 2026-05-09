from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from . import store_bp
from .models import Product, Order, StoreStaff
from models import db, User


def store_staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        is_admin = current_user.is_admin or current_user.role in ['admin', 'subadmin']
        is_staff = StoreStaff.query.filter_by(user_id=current_user.id).first()
        if not is_admin and not is_staff:
            flash('Access denied.', 'danger')
            return redirect(url_for('store.index'))
        return f(*args, **kwargs)
    return decorated


@store_bp.route('/dashboard')
@login_required
@store_staff_required
def store_dashboard():
    total_products = Product.query.count()
    active_products = Product.query.filter_by(is_active=True).count()
    total_orders = Order.query.count()
    paid_orders = Order.query.filter_by(status='paid').count()
    revenue = db.session.query(db.func.sum(Order.total_price)).filter(Order.status == 'paid').scalar() or 0
    return render_template('store/dashboard.html',
        total_products=total_products,
        active_products=active_products,
        total_orders=total_orders,
        paid_orders=paid_orders,
        revenue=revenue
    )


@store_bp.route('/dashboard/products')
@login_required
@store_staff_required
def dashboard_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('store/products.html', products=products)


@store_bp.route('/dashboard/products/add', methods=['GET', 'POST'])
@login_required
@store_staff_required
def dashboard_add_product():
    if request.method == 'POST':
        product = Product(
            name=request.form['name'].strip(),
            description=request.form.get('description', '').strip(),
            price=float(request.form['price']),
            stock=int(request.form.get('stock', 0)),
            image_url=request.form.get('image_url', '').strip(),
            is_active='is_active' in request.form
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added!', 'success')
        return redirect(url_for('store.dashboard_products'))
    return render_template('store/add_product.html')


@store_bp.route('/dashboard/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@store_staff_required
def dashboard_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form['name'].strip()
        product.description = request.form.get('description', '').strip()
        product.price = float(request.form['price'])
        product.stock = int(request.form.get('stock', 0))
        product.image_url = request.form.get('image_url', '').strip()
        product.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('store.dashboard_products'))
    return render_template('store/edit_product.html', product=product)


@store_bp.route('/dashboard/products/delete/<int:product_id>', methods=['POST'])
@login_required
@store_staff_required
def dashboard_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted!', 'success')
    return redirect(url_for('store.dashboard_products'))


@store_bp.route('/dashboard/orders')
@login_required
@store_staff_required
def dashboard_orders():
    status = request.args.get('status', '')
    query = Order.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(Order.created_at.desc()).all()
    return render_template('store/orders.html', orders=orders, current_status=status)


@store_bp.route('/dashboard/orders/update/<int:order_id>', methods=['POST'])
@login_required
@store_staff_required
def dashboard_update_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = request.form['status']
    db.session.commit()
    flash('Order status updated!', 'success')
    return redirect(url_for('store.dashboard_orders'))


@store_bp.route('/dashboard/staff')
@login_required
@store_staff_required
def dashboard_staff():
    staff_list = StoreStaff.query.all()
    return render_template('store/staff.html', staff_list=staff_list)


@store_bp.route('/dashboard/staff/add', methods=['POST'])
@login_required
@store_staff_required
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
    staff = StoreStaff(user_id=user.id, role=role)
    db.session.add(staff)
    db.session.commit()
    flash(f'{user.name} added as store {role}.', 'success')
    return redirect(url_for('store.dashboard_staff'))


@store_bp.route('/dashboard/staff/remove/<int:staff_id>', methods=['POST'])
@login_required
@store_staff_required
def dashboard_remove_staff(staff_id):
    staff = StoreStaff.query.get_or_404(staff_id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff member removed.', 'success')
    return redirect(url_for('store.dashboard_staff'))
