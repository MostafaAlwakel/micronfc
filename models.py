from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Personal Info
    phone = db.Column(db.String(20))
    job_title = db.Column(db.String(100))
    bio = db.Column(db.Text)

    # Profile Media
    profile_photo = db.Column(db.String(200))
    cover_photo = db.Column(db.String(200))

    # Social Links
    linkedin = db.Column(db.String(200))
    github = db.Column(db.String(200))
    twitter = db.Column(db.String(200))
    instagram = db.Column(db.String(200))
    whatsapp = db.Column(db.String(20))
    website = db.Column(db.String(200))
    snapchat = db.Column(db.String(200))
    facebook = db.Column(db.String(200))
    tiktok = db.Column(db.String(200))
    youtube = db.Column(db.String(200))
    product_type = db.Column(db.String(10), default='card')

    # Profile Extras
    location_url = db.Column(db.String(500))
    instapay = db.Column(db.String(200))
    portfolio_images = db.Column(db.Text)   # JSON array of filenames
    card_theme = db.Column(db.String(20), default='dark')
    extra_links = db.Column(db.Text)        # JSON array [{title, url}]

    # Medical Info
    blood_type = db.Column(db.String(5))
    allergies = db.Column(db.Text)
    chronic_diseases = db.Column(db.Text)
    medications = db.Column(db.Text)
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(20))
    doctor_name = db.Column(db.String(100))
    doctor_phone = db.Column(db.String(20))

    # Bot
    bot_context = db.Column(db.Text)

    # Admin & Access
    is_admin = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default='user')  # user / subadmin / admin
    is_active = db.Column(db.Boolean, default=True)

    # Email Verification
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), nullable=True)

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f'<User {self.email}>'

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    card_type = db.Column(db.String(20), default='smart')  # smart / medical
    activated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref='cards')

    def __repr__(self):
        return f'<Card {self.code}>'