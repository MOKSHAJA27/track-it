from flask import render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_user, logout_user, login_required, current_user, UserMixin
from flask_socketio import emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import pytz
import random
import logging
import base64
import io

from app import app, supabase, socketio
from qr_handler import generate_package_qr, generate_customer_delivery_qr, validate_qr_code, get_qr_image_data
from ai_predictions import get_ai_predictions

IST = pytz.timezone('Asia/Kolkata')

def format_ist(dt_str):
    if not dt_str:
        return "-"
    try:
        dt = datetime.fromisoformat(dt_str)
        # If naive, assume UTC and convert
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        dt = dt.astimezone(IST)
        return dt.strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return dt_str

STATUS_DISPLAY = {
    "pending": "Pending",
    "confirmed": "Confirmed",
    "accepted": "Accepted",
    "dispatched": "Dispatched",
    "in_transit": "In Transit",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
    "rejected": "Rejected",
}

def get_status_display(order):
    return STATUS_DISPLAY.get(order.get("status"), "Unknown")

class User(UserMixin):
    def __init__(self, id_, username, email, full_name, phone, address, role, successful_orders=0):
        self.id = id_
        self.username = username
        self.email = email
        self.full_name = full_name
        self.phone = phone
        self.address = address
        self.role = role
        self.successful_orders = successful_orders

    @staticmethod
    def get(user_id):
        response = supabase.table("users").select("*").eq("id", user_id).single().execute()
        data = response.data
        if data:
            return User(
                data["id"], data["username"], data["email"], data.get("full_name", ""),
                data.get("phone", ""), data.get("address", ""), data.get("role", ""), data.get("successful_orders", 0)
            )
        return None

    def check_password(self, password):
        response = supabase.table("users").select("password_hash").eq("id", self.id).single().execute()
        data = response.data
        return data and check_password_hash(data["password_hash"], password)

    def can_use_ai_predictions(self):
        return self.role == 'customer' and getattr(self, 'successful_orders', 0) >= 5

from app import login_manager
@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route('/')
def index():
    try:
        if current_user.is_authenticated:
            if current_user.role == 'customer':
                return redirect(url_for('customer_dashboard'), code=302)
            elif current_user.role == 'vendor':
                return redirect(url_for('vendor_dashboard'), code=302)
            elif current_user.role == 'delivery_partner':
                return redirect(url_for('delivery_dashboard'), code=302)
        return redirect(url_for('login'), code=302)
    except Exception as e:
        logging.error(f"Error in index route: {str(e)}")
        return redirect(url_for('login'), code=302)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        response = supabase.table("users").select("*").eq("username", username).execute()
        users = response.data or []
        if not users:
            flash('Invalid username or password.', 'error')
            return render_template('login.html')
        user_data = users[0]
        if user_data and check_password_hash(user_data.get("password_hash", ""), password):
            user = User(
                user_data["id"], user_data["username"], user_data["email"], user_data.get("full_name", ""),
                user_data.get("phone", ""), user_data.get("address", ""), user_data.get("role", ""), user_data.get("successful_orders", 0)
            )
            login_user(user)
            flash(f'Welcome {user.full_name}!', 'success')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page, code=302)
            if user.role == 'customer':
                return redirect(url_for('customer_dashboard'), code=302)
            elif user.role == 'vendor':
                return redirect(url_for('vendor_dashboard'), code=302)
            elif user.role == 'delivery_partner':
                return redirect(url_for('delivery_dashboard'), code=302)
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        full_name = request.form['full_name']
        phone = request.form['phone']
        address = request.form['address']
        role = request.form['role']

        if supabase.table("users").select("id").eq("username", username).execute().data:
            flash('Username already exists.', 'error')
            return render_template('register.html')
        if supabase.table("users").select("id").eq("email", email).execute().data:
            flash('Email already registered.', 'error')
            return render_template('register.html')

        password_hash = generate_password_hash(password)
        new_user = {
            "username": username, "email": email, "password_hash": password_hash,
            "full_name": full_name, "phone": phone, "address": address, "role": role,
            "created_at": datetime.now(IST).isoformat(), "successful_orders": 0
        }
        inserted = supabase.table("users").insert(new_user).execute()
        if not inserted.data:
            flash('User registration failed. Try again.', 'error')
            return render_template('register.html')

        if role == 'vendor':
            business_name = request.form.get('business_name', '')
            business_type = request.form.get('business_type', '')
            user_id = inserted.data[0]['id']
            vendor = {
                "user_id": user_id,
                "business_name": business_name,
                "business_type": business_type,
                "is_active": True,
                "created_at": datetime.now(IST).isoformat()
            }
            supabase.table("vendors").insert(vendor).execute()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    try:
        logout_user()
        flash('Successfully logged out.', 'info')
        return redirect(url_for('login'), code=302)
    except Exception as e:
        logging.error(f"Error during logout: {str(e)}")
        flash('Error during logout. Please try again.', 'error')
        return redirect(url_for('login'), code=302)

@app.route('/customer_dashboard')
@login_required
def customer_dashboard():
    if current_user.role != 'customer':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))
    orders = supabase.table("orders").select("*").eq("customer_id", current_user.id).order("created_at", desc=True).execute().data or []

    vendor_ids = list({order["vendor_id"] for order in orders if order.get("vendor_id")})
    vendors_data = supabase.table("vendors").select("*").in_("user_id", vendor_ids).execute().data or []
    vendors_by_id = {v["user_id"]: v for v in vendors_data}
    vendor_users = supabase.table("users").select("*").in_("id", vendor_ids).execute().data or []
    vendor_users_by_id = {u["id"]: u for u in vendor_users}
    for order in orders:
        vendor_id = order.get("vendor_id")
        order["vendor"] = {
            "vendor_profile": vendors_by_id.get(vendor_id, {}),
            "full_name": vendor_users_by_id.get(vendor_id, {}).get("full_name", ""),
            "phone": vendor_users_by_id.get(vendor_id, {}).get("phone", ""),
            "address": vendor_users_by_id.get(vendor_id, {}).get("address", "")
        }
        order["status_display"] = get_status_display(order)
        # Add formatted IST times
        order["created_at_ist"] = format_ist(order.get("created_at"))
        order["delivered_at_ist"] = format_ist(order.get("delivered_at"))

    active_orders = [o for o in orders if o.get("status") != "delivered"]
    completed_orders = [o for o in orders if o.get("status") == "delivered"]

    return render_template(
        'customer_dashboard.html',
        active_orders=active_orders,
        completed_orders=completed_orders
    )

@app.route('/vendor_dashboard')
@login_required
def vendor_dashboard():
    if current_user.role != 'vendor':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))

    pending_orders = supabase.table("orders").select("*").eq("vendor_id", current_user.id).eq("status", "pending").execute().data or []
    active_orders = supabase.table("orders").select("*").eq("vendor_id", current_user.id).in_("status", ["accepted", "dispatched", "in_transit", "out_for_delivery"]).order("created_at", desc=True).execute().data or []
    completed_orders = supabase.table("orders").select("*").eq("vendor_id", current_user.id).in_("status", ["delivered", "rejected"]).order("created_at", desc=True).limit(10).execute().data or []

    all_orders = pending_orders + active_orders + completed_orders
    customer_ids = list({o.get("customer_id") for o in all_orders if o.get("customer_id")})

    customers_by_id = {}
    if customer_ids:
        customers = supabase.table("users").select("id, full_name, phone, address").in_("id", customer_ids).execute().data or []
        customers_by_id = {c["id"]: c for c in customers}

    delivery_partner_ids = list({o.get("delivery_partner_id") for o in all_orders if o.get("delivery_partner_id")})
    delivery_partners_by_id = {}
    if delivery_partner_ids:
        dps = supabase.table("users").select("id, full_name, phone").in_("id", delivery_partner_ids).execute().data or []
        delivery_partners_by_id = {d["id"]: d for d in dps}

    def format_created_at(iso_str):
        return format_ist(iso_str)
    def format_delivered_at(iso_str):
        return format_ist(iso_str)

    for order in all_orders:
        order["customer"] = customers_by_id.get(order.get("customer_id"), {})
        order["formatted_created_at"] = format_created_at(order.get("created_at"))
        order["status_display"] = get_status_display(order)
        delivered_at = order.get("delivered_at")
        order["formatted_delivered_at"] = format_delivered_at(delivered_at) if delivered_at else ""
        order["delivery_partner"] = delivery_partners_by_id.get(order.get("delivery_partner_id"))

    # --- QR IMAGE PATCH START ---
    for order in active_orders:
        if order.get("package_qr_code"):
            order["package_qr_image"] = get_qr_image_data(order["package_qr_code"])
        else:
            order["package_qr_image"] = None
    # --- QR IMAGE PATCH END ---

    return render_template(
        'vendor_dashboard.html',
        pending_orders=pending_orders,
        active_orders=active_orders,
        completed_orders=completed_orders
    )

@app.route('/delivery_dashboard')
@login_required
def delivery_dashboard():
    if current_user.role != 'delivery_partner':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))

    # Assigned orders: not yet delivered/rejected/cancelled
    assigned_orders = supabase.table("orders") \
        .select("*") \
        .eq("delivery_partner_id", current_user.id) \
        .in_("status", ["accepted", "dispatched", "in_transit", "out_for_delivery"]) \
        .order("created_at", desc=True) \
        .execute().data or []

    # Completed orders: delivered in last 30 days
    now = datetime.now(IST)
    last_30_days = (now - timedelta(days=30)).isoformat()
    completed_orders = supabase.table("orders") \
        .select("*") \
        .eq("delivery_partner_id", current_user.id) \
        .eq("status", "delivered") \
        .gte("delivered_at", last_30_days) \
        .order("delivered_at", desc=True) \
        .execute().data or []

    # Total completed all time (for stats)
    total_completed_deliveries = supabase.table("orders") \
        .select("id") \
        .eq("delivery_partner_id", current_user.id) \
        .eq("status", "delivered") \
        .execute().data
    total_completed_deliveries = len(total_completed_deliveries) if total_completed_deliveries else 0

    # Attach customer and vendor info to each order for the template
    user_ids = set()
    for order in assigned_orders + completed_orders:
        if order.get("customer_id"):
            user_ids.add(order["customer_id"])
        if order.get("vendor_id"):
            user_ids.add(order["vendor_id"])

    users_map = {}
    if user_ids:
        users = supabase.table("users").select("*").in_("id", list(user_ids)).execute().data or []
        for user in users:
            users_map[user["id"]] = user

    # Attach vendor_profile if needed (for vendors)
    vendor_user_ids = {order["vendor_id"] for order in assigned_orders + completed_orders if order.get("vendor_id")}
    vendors_map = {}
    if vendor_user_ids:
        vendors = supabase.table("vendors").select("*").in_("user_id", list(vendor_user_ids)).execute().data or []
        for vendor in vendors:
            vendors_map[vendor["user_id"]] = vendor

    def get_status_display(order):
        return STATUS_DISPLAY.get(order.get("status"), "Unknown")

    # Attach and format info for template
    for order in assigned_orders + completed_orders:
        order["customer"] = users_map.get(order.get("customer_id"), {})
        vendor_user = users_map.get(order.get("vendor_id"), {})
        order["vendor"] = {
            **vendor_user,
            "vendor_profile": vendors_map.get(order.get("vendor_id"), {})
        }
        order["get_status_display"] = lambda o=order: get_status_display(o)
        order["qr_scan_count"] = order.get("qr_scan_count", 0)
        # Add formatted IST times
        order["formatted_created_at"] = format_ist(order.get("created_at"))
        order["formatted_delivered_at"] = format_ist(order.get("delivered_at"))

    # Create a serializable version for JS
    assigned_orders_for_js = []
    for order in assigned_orders:
        assigned_orders_for_js.append({
            "id": order["id"],
            "customer": {
                "full_name": order["customer"].get("full_name", ""),
                "phone": order["customer"].get("phone", ""),
                "address": order["customer"].get("address", ""),
            }
        })

    return render_template(
        'delivery_dashboard.html',
        assigned_orders=assigned_orders,
        completed_orders=completed_orders,
        total_completed_deliveries=total_completed_deliveries,
        assigned_orders_for_js=assigned_orders_for_js
    )
@app.route('/order/<int:order_id>/details')
@login_required
def order_details(order_id):
    order_resp = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    order = order_resp.data

    if not order:
        return jsonify({'error': 'Order not found'}), 404

    customer = supabase.table("users").select("full_name, phone, address").eq("id", order["customer_id"]).single().execute().data
    vendor = supabase.table("users").select("full_name, phone, address").eq("id", order["vendor_id"]).single().execute().data
    delivery_partner = None
    if order.get("delivery_partner_id"):
        delivery_partner = supabase.table("users").select("full_name, phone").eq("id", order["delivery_partner_id"]).single().execute().data

    def fmt(dt):
        return format_ist(dt)

    result = {
        'id': order["id"],
        'status': order.get("status"),
        'status_display': STATUS_DISPLAY.get(order.get("status"), "Unknown"),
        'order_description': order.get("order_description", ""),
        'window_time': order.get("window_time", ""),
        'delivery_speed': order.get("delivery_speed", ""),
        'created_at': fmt(order.get("created_at", "")),
        'accepted_at': fmt(order.get("accepted_at", "")) if order.get("accepted_at") else "",
        'delivered_at': fmt(order.get("delivered_at", "")) if order.get("delivered_at") else "",
        'estimated_amount': order.get("estimated_amount"),
        'final_amount': order.get("final_amount"),
        'package_qr_code': order.get("package_qr_code"),
        'delivery_qr_code': order.get("delivery_qr_code"),
        'customer': customer,
        'vendor': vendor,
        'delivery_partner': delivery_partner,
    }
    return jsonify(result)

def get_available_vendors():
    vendors = supabase.table("vendors").select("*").eq("is_active", True).execute().data or []
    vendor_ids = [v["user_id"] for v in vendors]
    vendor_users = supabase.table("users").select("*").in_("id", vendor_ids).execute().data or []
    users_by_id = {u["id"]: u for u in vendor_users}
    for v in vendors:
        u = users_by_id.get(v["user_id"]) or {}
        v["phone"] = u.get("phone", "")
        v["address"] = u.get("address", "")
        v["full_name"] = u.get("full_name", "")
        v["id"] = v["user_id"]
    return vendors

@app.route('/create_order', methods=['GET', 'POST'])
@login_required
def create_order():
    if current_user.role != 'customer':
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))
    if request.method == 'POST':
        vendor_id = request.form.get('vendor_id')
        order_description = request.form.get('order_description', '').strip()
        window_time = request.form.get('window_time')
        delivery_speed = request.form.get('delivery_speed')
        if not vendor_id:
            flash('Please select a vendor.', 'error')
            vendors = get_available_vendors()
            predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
            return render_template('create_order.html', vendors=vendors, predictions=predictions)
        if not order_description:
            flash('Please provide order description.', 'error')
            vendors = get_available_vendors()
            predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
            return render_template('create_order.html', vendors=vendors, predictions=predictions)
        if not window_time or window_time not in ['9am-12pm', '12pm-4pm', '5pm-9pm', '9pm-9am']:
            flash('Please select a valid delivery window.', 'error')
            vendors = get_available_vendors()
            predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
            return render_template('create_order.html', vendors=vendors, predictions=predictions)
        if not delivery_speed or delivery_speed not in ['express', 'regular']:
            flash('Please select a valid delivery speed.', 'error')
            vendors = get_available_vendors()
            predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
            return render_template('create_order.html', vendors=vendors, predictions=predictions)
        base_amount = 100
        estimated_amount = base_amount + 50 if delivery_speed == 'express' else base_amount

        # --- DUPLICATE CHECK START ---
        existing = supabase.table("orders").select("*") \
            .eq("customer_id", current_user.id) \
            .eq("vendor_id", int(vendor_id)) \
            .eq("order_description", order_description) \
            .eq("window_time", window_time) \
            .eq("delivery_speed", delivery_speed) \
            .eq("status", "pending") \
            .execute().data
        if existing:
            flash('You already have a similar pending order. Please wait for it to be processed before placing again.', 'warning')
            vendors = get_available_vendors()
            predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
            return render_template('create_order.html', vendors=vendors, predictions=predictions)
        # --- DUPLICATE CHECK END ---

        order_dict = {
            "customer_id": current_user.id,
            "vendor_id": int(vendor_id),
            "order_description": order_description,
            "window_time": window_time,
            "delivery_speed": delivery_speed,
            "status": "pending",
            "estimated_amount": estimated_amount,
            "created_at": datetime.now(IST).isoformat()
        }
        inserted = supabase.table("orders").insert(order_dict).execute()
        order = inserted.data[0] if inserted.data else None
        if order:
            socketio.emit('new_order', {
                'order_id': order["id"],
                'customer_name': current_user.full_name,
                'vendor_id': vendor_id,
                'description': order_description,
                'window_time': window_time,
                'delivery_speed': delivery_speed
            }, room=f'vendor_{vendor_id}')
            flash('Order placed successfully!', 'success')
            return redirect(url_for('customer_dashboard'))
        else:
            flash('Error placing order.', 'error')
    vendors = get_available_vendors()
    predictions = get_ai_predictions(current_user.id) if current_user.can_use_ai_predictions() else None
    return render_template('create_order.html', vendors=vendors, predictions=predictions)
@app.route('/order/<int:order_id>/accept', methods=['POST'])
@login_required
def accept_order(order_id):
    if current_user.role != 'vendor':
        return jsonify({'error': 'Unauthorized'}), 403
    order_resp = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    order = order_resp.data
    if not order or order["vendor_id"] != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if order["status"] != "pending":
        return jsonify({'error': 'Order cannot be accepted'}), 400
    accepted_at = datetime.now(IST).isoformat()
    qr_code = generate_package_qr(order_id)
    dps = supabase.table("users").select("id").eq("role", "delivery_partner").execute().data or []
    delivery_partner_id = random.choice(dps)["id"] if dps else None
    update_dict = {
        "status": "accepted", "accepted_at": accepted_at, "package_qr_code": qr_code,
        "delivery_partner_id": delivery_partner_id
    }
    supabase.table("orders").update(update_dict).eq("id", order_id).execute()
    customer = supabase.table("users").select("full_name").eq("id", order["customer_id"]).single().execute().data
    socketio.emit('order_status_update', {
        'order_id': order_id, 'status': 'accepted', 'timestamp': format_ist(accepted_at), 'qr_code': qr_code
    }, room=f'customer_{order["customer_id"]}')
    if delivery_partner_id:
        vendor_name = current_user.full_name
        socketio.emit('new_assignment', {
            'order_id': order_id,
            'customer_name': customer["full_name"] if customer else "",
            'vendor_name': vendor_name,
            'description': order["order_description"]
        }, room=f'delivery_{delivery_partner_id}')
    return jsonify({'success': True, 'qr_code': qr_code, 'accepted': True})

@app.route('/order/<int:order_id>/reject', methods=['POST'])
@login_required
def reject_order(order_id):
    if current_user.role != 'vendor':
        return jsonify({'error': 'Unauthorized'}), 403
    order_resp = supabase.table("orders").select("*").eq("id", order_id).single().execute()
    order = order_resp.data
    if not order or order["vendor_id"] != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if order["status"] != "pending":
        return jsonify({'error': 'Order cannot be rejected'}), 400
    supabase.table("orders").update({"status": "rejected"}).eq("id", order_id).execute()
    socketio.emit('order_status_update', {
        'order_id': order_id, 'status': 'rejected', 'timestamp': format_ist(datetime.now(IST).isoformat())
    }, room=f'customer_{order["customer_id"]}')
    return jsonify({'success': True})

@app.route('/qr_scanner')
@login_required
def qr_scanner():
    if current_user.role not in ['delivery_partner', 'customer']:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('index'))
    return render_template('qr_scanner.html')

@app.route('/scan_qr', methods=['POST'])
@login_required
def scan_qr():
    qr_data = request.json.get('qr_data')
    if not qr_data:
        return jsonify({'error': 'No QR data provided'}), 400

    result = validate_qr_code(qr_data, current_user.id)

    if result['success']:
        order = result['order']
        update_data = {
            'order_id': order["id"],
            'status': order["status"],
            'timestamp': format_ist(datetime.now(IST).isoformat()),
            'scanned_by': current_user.full_name,
            'scan_type': result.get('scan_type', 'unknown')
        }
        if result.get('delivery_qr_generated'):
            update_data['delivery_qr_code'] = order.get("delivery_qr_code")

        # Emit live updates
        socketio.emit('order_status_update', update_data, room=f'customer_{order["customer_id"]}')
        socketio.emit('order_status_update', update_data, room=f'vendor_{order["vendor_id"]}')
        if order.get("delivery_partner_id"):
            socketio.emit('order_status_update', update_data, room=f'delivery_{order["delivery_partner_id"]}')
        socketio.emit('global_order_update', {
            'order_id': order["id"],
            'status': order["status"],
            'timestamp': update_data['timestamp']
        })
    return jsonify(result)

@app.route('/qr_image')
def qr_image():
    data = request.args.get('data')
    if not data:
        return '', 400
    img_data_url = get_qr_image_data(data)
    if not img_data_url or not img_data_url.startswith('data:image'):
        return '', 404
    base64_str = img_data_url.split(',')[1]
    img_bytes = base64.b64decode(base64_str)
    return send_file(io.BytesIO(img_bytes), mimetype='image/png')

@socketio.on('join_room')
def on_join(data):
    if current_user.is_authenticated:
        room = f"{current_user.role}_{current_user.id}"
        join_room(room)
        emit('status', {'msg': f'Joined room {room}'})

@socketio.on('leave_room')
def on_leave(data):
    if current_user.is_authenticated:
        room = f"{current_user.role}_{current_user.id}"
        leave_room(room)
        emit('status', {'msg': f'Left room {room}'})

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500