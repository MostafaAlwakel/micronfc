# v2
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from config import Config
from models import db, User, Card
import secrets
import resend
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from functools import wraps
import os
import json
import re
import requests
import cloudinary
import cloudinary.uploader

load_dotenv()
resend.api_key = os.getenv('RESEND_API_KEY')

# ==================== OPENROUTER SETUP ====================
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ==================== CLOUDINARY SETUP ====================
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

def upload_image(file):
    try:
        print(f"Cloudinary config: cloud={cloudinary.config().cloud_name}")
        result = cloudinary.uploader.upload(file)
        print(f"Upload success: {result['secure_url']}")
        return result['secure_url']
    except Exception as e:
        print(f"Cloudinary Error: {type(e).__name__}: {e}")
        return None

# ==================== APP SETUP ====================
app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
bcrypt = Bcrypt(app)
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value or '[]')
    except Exception:
        return []

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please login to complete your order.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== ADMIN DECORATOR ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_admin or current_user.role in ['admin', 'subadmin']):
            flash('Access denied!', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== STORE BLUEPRINT ====================
from store import store_bp
app.register_blueprint(store_bp)

# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        next_page = request.args.get('next', '').strip()
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        if User.query.filter_by(email=email).first():
            flash('Email already exists!', 'danger')
            return redirect(url_for('register'))

        token = secrets.token_urlsafe(32)
        user = User(name=name, email=email, password=password,
                   is_verified=False, verification_token=token)
        db.session.add(user)
        db.session.commit()

        # بعت إيميل التفعيل
        verify_url = f"https://www.micronfc.info/verify/{token}"
        try:
            resend.Emails.send({
                "from": "MicroNFC <noreply@micronfc.info>",
                "to": email,
                "subject": "Verify your MicroNFC account",
                "html": f"""
                <div style="font-family:sans-serif; max-width:480px; margin:0 auto; padding:2rem;">
                  <h2 style="color:#00e5a0;">Welcome to MicroNFC! 👋</h2>
                  <p>Hi {name}, please verify your email to activate your account.</p>
                  <a href="{verify_url}"
                     style="display:inline-block; background:#00e5a0; color:#000; padding:0.75rem 2rem;
                            border-radius:10px; text-decoration:none; font-weight:700; margin:1rem 0;">
                    Verify Email
                  </a>
                  <p style="color:#888; font-size:0.85rem;">If you didn't create this account, ignore this email.</p>
                </div>
                """
            })
        except Exception as e:
            print("Email error:", e)

        flash('Account created! Please check your email to verify your account.', 'success')
        next_page = request.args.get('next', '').strip()
        login_url = url_for('login')
        if next_page and next_page.startswith('/'):
            login_url = f'{login_url}?next={next_page}'
        return redirect(login_url)

    return render_template('register.html')

@app.route('/verify/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash('Invalid or expired verification link!', 'danger')
        return redirect(url_for('login'))
    user.is_verified = True
    user.verification_token = None
    db.session.commit()
    flash('Email verified! You can now login. ✅', 'success')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get('next', '').strip()
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            if not user.is_active:
                flash('Your account has been disabled!', 'danger')
                return redirect(url_for('login'))
            if not user.is_verified:
                flash('Please verify your email first! Check your inbox.', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            next_url = session.pop('redirect_after_login', None)
            if next_url:
                return redirect(next_url)
            next_page = request.args.get('next', '').strip()
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password!', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@app.route('/profile/<int:user_id>')
def public_profile(user_id):
    # بيشتغل بس لو جاي من كرت مفعّل
    ref = request.args.get('ref', '')
    card = Card.query.filter_by(code=ref, user_id=user_id).first()
    if not card:
        return render_template('card_invalid.html'), 403
    user = User.query.get_or_404(user_id)
    return render_template('card_profile.html', user=user)

@app.route('/medical/<int:user_id>')
def medical_profile(user_id):
    ref = request.args.get('ref', '')
    card = Card.query.filter_by(code=ref, user_id=user_id).first()
    if not card:
        return render_template('card_invalid.html'), 403
    user = User.query.get_or_404(user_id)
    return render_template('bracelet_profile.html', user=user)

@app.route('/edit/personal', methods=['GET', 'POST'])
@login_required
def edit_personal():
    if request.method == 'POST':
        current_user.name = request.form['name']
        current_user.phone = request.form['phone']
        current_user.job_title = request.form['job_title']
        current_user.bio = request.form['bio']

        # رفع صورة البروفايل على Cloudinary
        if 'profile_photo' in request.files:
            file = request.files['profile_photo']
            if file and file.filename:
                url = upload_image(file)
                if url:
                    current_user.profile_photo = url

        # رفع صورة الخلفية على Cloudinary
        if 'cover_photo' in request.files:
            file = request.files['cover_photo']
            if file and file.filename:
                url = upload_image(file)
                if url:
                    current_user.cover_photo = url

        db.session.commit()
        flash('Personal info updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_personal.html', user=current_user)

@app.route('/edit/social', methods=['GET', 'POST'])
@login_required
def edit_social():
    if request.method == 'POST':
        current_user.linkedin = request.form['linkedin']
        current_user.github = request.form['github']
        current_user.twitter = request.form['twitter']
        current_user.instagram = request.form['instagram']
        current_user.whatsapp = request.form['whatsapp']
        current_user.website = request.form['website']
        current_user.snapchat = request.form['snapchat']
        current_user.facebook = request.form['facebook']
        current_user.tiktok = request.form['tiktok']
        current_user.youtube = request.form['youtube']
        db.session.commit()
        flash('Social links updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_social.html', user=current_user)

def extract_instapay_link(text):
    match = re.search(r'https://ipn\.eg/S/[^\s]+', text)
    if match:
        return match.group(0)
    return None

@app.route('/edit/extras', methods=['GET', 'POST'])
@login_required
def edit_extras():
    if request.method == 'POST':
        current_user.location_url = request.form['location_url']
        raw = request.form.get('instapay', '').strip()
        if raw:
            instapay_link = extract_instapay_link(raw)
            if not instapay_link:
                flash('الرابط غير صحيح، تأكد إنه يحتوي على رابط InstaPay', 'danger')
                return render_template('edit_extras.html', user=current_user, instapay_raw=raw)
            current_user.instapay = instapay_link
        else:
            current_user.instapay = ''
        db.session.commit()
        flash('Location & payment info updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_extras.html', user=current_user)

@app.route('/edit/theme', methods=['GET', 'POST'])
@login_required
def edit_theme():
    if request.method == 'POST':
        current_user.card_theme = request.form.get('card_theme', 'dark')
        db.session.commit()
        flash('Card theme updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_theme.html', user=current_user)

@app.route('/edit/portfolio', methods=['GET', 'POST'])
@login_required
def edit_portfolio():
    if request.method == 'POST':
        images = json.loads(current_user.portfolio_images or '[]')
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                url = upload_image(file)
                if url:
                    images.append(url)
                    current_user.portfolio_images = json.dumps(images)
                    db.session.commit()
                    flash('Image added!', 'success')
        return redirect(url_for('edit_portfolio'))
    images = json.loads(current_user.portfolio_images or '[]')
    return render_template('edit_portfolio.html', user=current_user, images=images)

@app.route('/edit/portfolio/delete', methods=['POST'])
@login_required
def delete_portfolio_image():
    url = request.form.get('filename')
    images = json.loads(current_user.portfolio_images or '[]')
    if url in images:
        images.remove(url)
        current_user.portfolio_images = json.dumps(images)
        db.session.commit()
    flash('Image removed!', 'success')
    return redirect(url_for('edit_portfolio'))

@app.route('/edit/links', methods=['GET', 'POST'])
@login_required
def edit_links():
    if request.method == 'POST':
        titles = request.form.getlist('title[]')
        urls = request.form.getlist('url[]')
        links = [{'title': t.strip(), 'url': u.strip()} for t, u in zip(titles, urls) if t.strip() and u.strip()]
        current_user.extra_links = json.dumps(links)
        db.session.commit()
        flash('Custom links updated!', 'success')
        return redirect(url_for('dashboard'))
    links = json.loads(current_user.extra_links or '[]')
    return render_template('edit_links.html', user=current_user, links=links)

@app.route('/edit/medical', methods=['GET', 'POST'])
@login_required
def edit_medical():
    if request.method == 'POST':
        current_user.blood_type = request.form['blood_type']
        current_user.allergies = request.form['allergies']
        current_user.chronic_diseases = request.form['chronic_diseases']
        current_user.medications = request.form['medications']
        current_user.emergency_contact_name = request.form['emergency_contact_name']
        current_user.emergency_contact_phone = request.form['emergency_contact_phone']
        current_user.doctor_name = request.form['doctor_name']
        current_user.doctor_phone = request.form['doctor_phone']
        db.session.commit()
        flash('Medical info updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_medical.html', user=current_user)

@app.route('/edit/bot', methods=['GET', 'POST'])
@login_required
def edit_bot():
    if request.method == 'POST':
        current_user.bot_context = request.form['bot_context']
        current_user.medical_chatbot_name = request.form.get('medical_chatbot_name', 'Medical Assistant').strip() or 'Medical Assistant'
        current_user.medical_chatbot_prompt = request.form.get('medical_chatbot_prompt', '')
        db.session.commit()
        flash('Bot updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('edit_bot.html', user=current_user)

@app.route('/chat', methods=['GET'])
@login_required
def chat():
    return render_template('chat.html', user=current_user)

# ==================== API CHAT (للمستخدم المسجل) ====================

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    user_message = data.get('message', '')

    chat_key = f'chat_history_{current_user.id}'
    if chat_key not in session:
        session[chat_key] = []

    system_prompt = f"""You are a smart personal AI assistant representing {current_user.name}.
You speak ON BEHALF of this person to anyone who visits their profile.

Everything you know about them:
{current_user.bot_context or 'No information provided yet.'}

Rules:
- You represent {current_user.name}, not the person chatting with you
- For questions ABOUT {current_user.name}: answer using only the info above
- For general questions (science, tech, advice, etc): answer helpfully as {current_user.name}'s assistant
- If asked something personal not in the data, say: "I don't have that info, contact {current_user.name} directly"
- Always be friendly, natural, and conversational
- Never say you are an AI language model — you are {current_user.name}'s personal assistant"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += session[chat_key]
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {"model": "gpt-4o-mini", "messages": messages}

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        reply = result['choices'][0]['message']['content']

        session[chat_key].append({"role": "user", "content": user_message})
        session[chat_key].append({"role": "assistant", "content": reply})

        if len(session[chat_key]) > 20:
            session[chat_key] = session[chat_key][-20:]

        session.modified = True
        return jsonify({'response': reply})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({'response': 'Error: ' + str(e)})


@app.route('/api/chat/clear', methods=['POST'])
@login_required
def clear_chat():
    chat_key = f'chat_history_{current_user.id}'
    session.pop(chat_key, None)
    return jsonify({'status': 'cleared'})


@app.route('/api/support_chat', methods=['POST'])
@login_required
def support_chat():
    data = request.get_json()
    message = data.get('message', '')
    history = data.get('history', [])

    system_prompt = """You are MicroNFC's official customer support assistant.

About MicroNFC:
- We sell smart NFC cards and medical bracelets in Egypt
- Smart NFC Card: links to a digital profile with AI chatbot (199 EGP)
- Medical NFC Bracelet: stores emergency medical information (299 EGP)
- Website: micronfc.info
- Support Email: support@micronfc.info

Subscription Plans:
- Free Plan: 20 messages/month for your AI bot
- Pro Plan: 1000 messages/month for 100 EGP/month

How to order:
- Visit micronfc.info/store
- Complete checkout with your details
- Card will be delivered within 2-3 business days

Common questions:
- Card not working: make sure NFC is enabled on your phone settings
- Bot not responding: check your message limit on dashboard
- Update profile: go to dashboard and click Edit Profile
- Track order: go to micronfc.info/store/my-orders
- Cancel subscription: contact support@micronfc.info

If you cannot resolve an issue, always direct the user to support@micronfc.info

Always respond in the same language the user writes in (Arabic or English).
Be friendly, helpful, and concise."""

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-10:]:
        messages.append({'role': h['role'], 'content': h['content']})
    messages.append({"role": "user", "content": message})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"model": "gpt-4o-mini", "messages": messages}

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        reply = result['choices'][0]['message']['content']
        return jsonify({'response': reply})
    except Exception as e:
        print("ERROR:", e)
        return jsonify({'response': 'عذراً، حدث خطأ. يرجى المحاولة مجدداً.'})


# ==================== API CHAT (للزوار بدون login) ====================

@app.route('/api/public_chat/<int:user_id>', methods=['POST'])
def public_chat(user_id):
    user = User.query.get_or_404(user_id)

    # Check monthly reset
    from datetime import datetime
    now = datetime.utcnow()
    if user.plan_reset_date:
        if now.month != user.plan_reset_date.month or now.year != user.plan_reset_date.year:
            user.messages_used = 0
            user.plan_reset_date = now
            db.session.commit()

    # Check limit
    if (user.messages_used or 0) >= (user.messages_limit or 20):
        return jsonify({
            'response': 'عذراً، انتهت رسائل البوت لهذا الشهر.',
            'limit_reached': True
        })

    data = request.get_json()
    user_message = data.get('message', '')

    card_type = data.get('card_type', 'personal')
    chat_key = f'public_chat_{user_id}_{card_type}'
    if chat_key not in session:
        session[chat_key] = []

    if card_type == 'medical':
        system_prompt = f"""You are a medical emergency AI assistant for {user.name}.
Medical information:
{user.medical_chatbot_prompt or f'Blood type: {user.blood_type or "Unknown"}, Allergies: {user.allergies or "None listed"}, Medications: {user.medications or "None listed"}, Emergency contact: {user.emergency_contact_name or "Not provided"}'}

Rules:
- Provide calm, clear emergency guidance
- Share medical info (blood type, allergies, conditions, medications) when asked
- Always recommend calling emergency services (123 in Egypt) for critical cases
- Never replace professional medical advice
- Be concise and clear in emergencies
- Respond in the same language the visitor uses (Arabic or English)"""
    else:
        system_prompt = f"""You are a smart personal AI assistant representing {user.name}.
You speak ON BEHALF of this person to anyone who visits their profile.

Everything you know about them:
{user.bot_context or 'No information provided yet.'}

Rules:
- You represent {user.name}, not the person chatting with you
- For questions ABOUT {user.name}: answer using only the info above
- For general questions (science, tech, advice, etc): answer helpfully as {user.name}'s assistant
- If asked something personal not in the data, say: "I don't have that info, contact {user.name} directly"
- Always be friendly, natural, and conversational
- Never say you are an AI language model — you are {user.name}'s personal assistant
- Respond in the same language the visitor uses (Arabic or English)"""

    messages = [{"role": "system", "content": system_prompt}]
    messages += session[chat_key]
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {"model": "gpt-4o-mini", "messages": messages}

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        reply = result['choices'][0]['message']['content']

        session[chat_key].append({"role": "user", "content": user_message})
        session[chat_key].append({"role": "assistant", "content": reply})

        if len(session[chat_key]) > 20:
            session[chat_key] = session[chat_key][-20:]

        session.modified = True
        user.messages_used = (user.messages_used or 0) + 1
        user.total_messages_ever = (user.total_messages_ever or 0) + 1
        db.session.commit()
        return jsonify({'response': reply})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({'response': 'Error: ' + str(e)})


@app.route('/api/public_chat/clear/<int:user_id>', methods=['POST'])
def clear_public_chat(user_id):
    session.pop(f'public_chat_{user_id}_personal', None)
    session.pop(f'public_chat_{user_id}_medical', None)
    session.pop(f'public_chat_{user_id}', None)
    return jsonify({'status': 'cleared'})


@app.route('/set_product/<ptype>')
@login_required
def set_product(ptype):
    if ptype in ['card', 'bracelet']:
        current_user.product_type = ptype
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/preview/<int:user_id>')
@login_required
def preview_profile(user_id):
    if current_user.id != user_id and not current_user.is_admin:
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    return render_template('card_profile.html', user=user)

@app.route('/preview/medical/<int:user_id>')
@login_required
def preview_medical(user_id):
    if current_user.id != user_id and not current_user.is_admin:
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    return render_template('bracelet_profile.html', user=user)

# ==================== CARDS ====================

@app.route('/c/<code>')
def card_redirect(code):
    card = Card.query.filter_by(code=code).first()
    if not card or not card.is_active:
        return render_template('card_invalid.html'), 404
    if not card.user_id:
        return render_template('card_not_activated.html'), 404
    user = User.query.get(card.user_id)
    if not user or not user.is_active:
        return render_template('card_invalid.html'), 404
    if card.card_type == 'medical':
        return redirect(url_for('medical_profile', user_id=user.id, ref=card.code))
    return redirect(url_for('public_profile', user_id=user.id, ref=card.code))

@app.route('/activate', methods=['POST'])
@login_required
def activate_card():
    code = request.form.get('code', '').strip().upper()
    card = Card.query.filter_by(code=code).first()

    if not card:
        flash('Invalid card code!', 'danger')
        return redirect(url_for('dashboard'))

    if card.user_id:
        flash('This card is already activated!', 'danger')
        return redirect(url_for('dashboard'))

    if not card.is_active:
        flash('This card is disabled!', 'danger')
        return redirect(url_for('dashboard'))

    from datetime import datetime, timezone
    card.user_id = current_user.id
    card.activated_at = datetime.now(timezone.utc)
    db.session.commit()

    card_type = '⌚ Medical Bracelet' if card.card_type == 'medical' else '🪪 Smart Card'
    flash(f'{card_type} activated successfully! 🎉', 'success')
    return redirect(url_for('dashboard'))

# ==================== GOOGLE LOGIN ====================

@app.route('/auth/google')
def google_login():
    redirect_uri = 'https://www.micronfc.info/auth/google/callback'
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')

    if not user_info:
        flash('Google login failed!', 'danger')
        return redirect(url_for('login'))

    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])

    user = User.query.filter_by(email=email).first()

    if not user:
        # عمل حساب جديد تلقائياً
        password = bcrypt.generate_password_hash(secrets.token_hex(16)).decode('utf-8')
        user = User(
            name=name,
            email=email,
            password=password,
            is_verified=True,
            is_active=True,
            role='user'
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Welcome {name}! Your account has been created. 🎉', 'success')
    else:
        if not user.is_active:
            flash('Your account has been disabled!', 'danger')
            return redirect(url_for('login'))

    login_user(user)
    next_url = session.pop('redirect_after_login', None)
    if next_url:
        return redirect(next_url)
    return redirect(url_for('dashboard'))

# ==================== UPGRADE / SUBSCRIPTION ====================

@app.route('/upgrade', methods=['GET', 'POST'])
@login_required
def upgrade():
    if request.method == 'POST':
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'egp',
                    'product_data': {
                        'name': 'MicroNFC Pro - AI Chatbot',
                        'description': '1000 رسالة شهرياً للبوت الخاص بك',
                    },
                    'unit_amount': 10000,
                    'recurring': {'interval': 'month'},
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'upgrade/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'dashboard',
            metadata={'user_id': str(current_user.id)},
        )
        return redirect(checkout_session.url, code=303)
    return render_template('upgrade.html')


@app.route('/upgrade/success')
@login_required
def upgrade_success():
    session_id = request.args.get('session_id')
    if session_id:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        if checkout_session.payment_status == 'paid':
            from datetime import datetime
            current_user.plan = 'pro'
            current_user.messages_limit = 1000
            current_user.messages_used = 0
            current_user.stripe_subscription_id = checkout_session.subscription
            db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/webhook/subscription', methods=['POST'])
def subscription_webhook():
    import stripe
    stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET')
        )
    except Exception:
        return jsonify({'error': 'Invalid signature'}), 400
    if event['type'] == 'invoice.paid':
        sub_id = event['data']['object']['subscription']
        user = User.query.filter_by(stripe_subscription_id=sub_id).first()
        if user:
            from datetime import datetime
            user.messages_used = 0
            user.plan_reset_date = datetime.utcnow()
            db.session.commit()
    if event['type'] == 'customer.subscription.deleted':
        sub_id = event['data']['object']['id']
        user = User.query.filter_by(stripe_subscription_id=sub_id).first()
        if user:
            user.plan = 'free'
            user.messages_limit = 20
            db.session.commit()
    return jsonify({'status': 'ok'})


# ==================== ADMIN ====================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    total_users = User.query.count()
    card_users = User.query.filter_by(product_type='card').count()
    bracelet_users = User.query.filter_by(product_type='bracelet').count()
    active_users = User.query.filter_by(is_active=True).count()
    pro_users_count = User.query.filter_by(plan='pro').count()
    free_users_count = User.query.filter_by(plan='free').count()
    top_bot_users = User.query.filter(
        User.total_messages_ever > 0
    ).order_by(User.total_messages_ever.desc()).limit(10).all()
    return render_template('admin.html',
        users=users,
        total_users=total_users,
        card_users=card_users,
        bracelet_users=bracelet_users,
        active_users=active_users,
        pro_users_count=pro_users_count,
        free_users_count=free_users_count,
        top_bot_users=top_bot_users,
    )

@app.route('/admin/add_user', methods=['POST'])
@login_required
@admin_required
def admin_add_user():
    name = request.form['name']
    email = request.form['email']
    password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
    role = request.form.get('role', 'user')

    if User.query.filter_by(email=email).first():
        flash('Email already exists!', 'danger')
        return redirect(url_for('admin_dashboard'))

    user = User(
        name=name, email=email, password=password, role=role,
        is_admin=True if role in ['admin', 'subadmin'] else False
    )
    db.session.add(user)
    db.session.commit()
    flash(f'User {name} added successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form['email']
        user.phone = request.form['phone']
        user.job_title = request.form['job_title']
        user.bio = request.form['bio']
        user.whatsapp = request.form['whatsapp']
        user.instagram = request.form['instagram']
        user.snapchat = request.form['snapchat']
        user.facebook = request.form['facebook']
        user.tiktok = request.form['tiktok']
        user.youtube = request.form['youtube']
        user.twitter = request.form['twitter']
        user.linkedin = request.form['linkedin']
        user.github = request.form['github']
        user.website = request.form['website']
        user.location_url = request.form['location_url']
        user.instapay = request.form['instapay']
        user.card_theme = request.form.get('card_theme', 'dark')
        titles = request.form.getlist('link_title[]')
        urls = request.form.getlist('link_url[]')
        links = [{'title': t.strip(), 'url': u.strip()} for t, u in zip(titles, urls) if t.strip() and u.strip()]
        user.extra_links = json.dumps(links)
        user.blood_type = request.form['blood_type']
        user.allergies = request.form['allergies']
        user.chronic_diseases = request.form['chronic_diseases']
        user.medications = request.form['medications']
        user.emergency_contact_name = request.form['emergency_contact_name']
        user.emergency_contact_phone = request.form['emergency_contact_phone']
        user.doctor_name = request.form['doctor_name']
        user.doctor_phone = request.form['doctor_phone']
        user.bot_context = request.form['bot_context']
        user.product_type = request.form['product_type']
        if current_user.is_admin and current_user.role == 'admin':
            user.role = request.form.get('role', 'user')
            user.is_admin = True if user.role in ['admin', 'subadmin'] else False
        db.session.commit()
        flash(f'User {user.name} updated!', 'success')
        return redirect(url_for('admin_dashboard'))
    links = json.loads(user.extra_links or '[]')
    images = json.loads(user.portfolio_images or '[]')
    return render_template('admin_edit_user.html', user=user, links=links, images=images)

@app.route('/admin/portfolio/upload/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_upload_portfolio(user_id):
    user = User.query.get_or_404(user_id)
    images = json.loads(user.portfolio_images or '[]')
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            url = upload_image(file)
            if url:
                images.append(url)
                user.portfolio_images = json.dumps(images)
                db.session.commit()
                flash('Image added!', 'success')
    return redirect(url_for('admin_edit_user', user_id=user_id) + '#portfolio')

@app.route('/admin/portfolio/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_portfolio(user_id):
    user = User.query.get_or_404(user_id)
    url = request.form.get('filename')
    images = json.loads(user.portfolio_images or '[]')
    if url in images:
        images.remove(url)
        user.portfolio_images = json.dumps(images)
        db.session.commit()
    flash('Image removed!', 'success')
    return redirect(url_for('admin_edit_user', user_id=user_id) + '#portfolio')

@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form['new_password']
    user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    db.session.commit()
    flash(f'Password reset for {user.name}!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle_active/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot disable main admin!', 'danger')
        return redirect(url_for('admin_dashboard'))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'disabled'
    flash(f'User {user.name} {status}!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot delete main admin!', 'danger')
        return redirect(url_for('admin_dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.name} deleted!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/set_product/<int:user_id>/<ptype>', methods=['POST'])
@login_required
@admin_required
def admin_set_product(user_id, ptype):
    user = User.query.get_or_404(user_id)
    if ptype in ['card', 'bracelet']:
        user.product_type = ptype
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/generate_cards', methods=['POST'])
@login_required
@admin_required
def admin_generate_cards():
    count = int(request.form.get('count', 1))
    card_type = request.form.get('card_type', 'smart')
    count = min(count, 100)
    generated = []
    for _ in range(count):
        while True:
            code = secrets.token_hex(4).upper()
            if not Card.query.filter_by(code=code).first():
                break
        card = Card(code=code, card_type=card_type)
        db.session.add(card)
        generated.append(code)
    db.session.commit()
    flash(f'{count} {card_type} card(s) generated!', 'success')
    return redirect(url_for('admin_cards'))

@app.route('/admin/cards')
@login_required
@admin_required
def admin_cards():
    cards = Card.query.order_by(Card.created_at.desc()).all()
    total = Card.query.count()
    activated = Card.query.filter(Card.user_id != None).count()
    return render_template('admin_cards.html',
        cards=cards,
        total=total,
        activated=activated
    )

@app.route('/admin/cards/delete/<int:card_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_card(card_id):
    card = Card.query.get_or_404(card_id)
    db.session.delete(card)
    db.session.commit()
    flash('Card deleted!', 'success')
    return redirect(url_for('admin_cards'))

@app.route('/admin/cards/toggle/<int:card_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_card(card_id):
    card = Card.query.get_or_404(card_id)
    card.is_active = not card.is_active
    db.session.commit()
    status = 'enabled' if card.is_active else 'disabled'
    flash(f'Card {card.code} {status}!', 'success')
    return redirect(url_for('admin_cards'))


@app.route('/admin/add-credits/<int:user_id>', methods=['POST'])
@login_required
def admin_add_credits(user_id):
    if current_user.role != 'admin':
        abort(403)
    user = User.query.get_or_404(user_id)
    credits = int(request.form.get('credits', 0))
    user.messages_limit = (user.messages_limit or 20) + credits
    db.session.commit()
    flash(f'تم إضافة {credits} رسالة لـ {user.name}', 'success')
    return redirect(url_for('admin_dashboard'))

# ==================== DB MIGRATION & STARTUP ====================

def migrate_db():
    from sqlalchemy import text
    new_cols = [
        ("snapchat", "VARCHAR(200)"),
        ("facebook", "VARCHAR(200)"),
        ("tiktok", "VARCHAR(200)"),
        ("youtube", "VARCHAR(200)"),
        ("location_url", "VARCHAR(500)"),
        ("instapay", "VARCHAR(200)"),
        ("portfolio_images", "TEXT"),
        ("card_theme", "VARCHAR(20) DEFAULT 'dark'"),
        ("extra_links", "TEXT"),
        ("role", "VARCHAR(20) DEFAULT 'user'"),
        ("is_active", "BOOLEAN DEFAULT TRUE"),
        ("profile_photo", "TEXT"),
        ("cover_photo", "TEXT"),
        ("instagram", "VARCHAR(200)"),
        ("whatsapp", "VARCHAR(20)"),
        ("bot_context", "TEXT"),
        ("is_admin", "BOOLEAN DEFAULT FALSE"),
        ("medical_chatbot_name", "VARCHAR(100) DEFAULT 'Medical Assistant'"),
        ("medical_chatbot_prompt", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        try:
            with db.engine.connect() as conn:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type}'))
                conn.commit()
        except Exception:
            pass

    # migrate card table
    try:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE card ADD COLUMN card_type VARCHAR(20) DEFAULT \'smart\''))
            conn.commit()
    except Exception:
        pass

    # migrate subscription columns
    subscription_cols = [
        ("plan", "VARCHAR(20) DEFAULT 'free'"),
        ("messages_used", "INTEGER DEFAULT 0"),
        ("messages_limit", "INTEGER DEFAULT 20"),
        ("plan_reset_date", "TIMESTAMP"),
        ("stripe_subscription_id", "VARCHAR(200)"),
        ("total_messages_ever", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_type in subscription_cols:
        try:
            with db.engine.connect() as conn:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type}'))
                conn.commit()
        except Exception:
            pass

    # migrate verification columns
    for col_name, col_type in [("is_verified", "BOOLEAN DEFAULT FALSE"), ("verification_token", "TEXT")]:
        try:
            with db.engine.connect() as conn:
                conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col_name} {col_type}'))
                conn.commit()
        except Exception:
            pass

    # migrate store_products table
    try:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE store_products ADD COLUMN images TEXT DEFAULT \'\''))
            conn.commit()
    except Exception:
        pass

with app.app_context():
    db.create_all()
    migrate_db()
    if not os.path.exists('static/uploads'):
        os.makedirs('static/uploads')

# ==================== STATIC PAGES ====================
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/refund')
def refund():
    return render_template('refund.html')

# ==================== RUN ====================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)