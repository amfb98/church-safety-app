from flask import Flask, render_template, request, redirect, url_for, flash, send_file, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import os
from PIL import Image
import uuid
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import pytz
from pywebpush import webpush, WebPushException
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'church_safety.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx'}
EASTERN = pytz.timezone('US/Eastern')

def to_eastern(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(EASTERN)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== MODELS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='member')
    is_safety_team = db.Column(db.Boolean, default=True)
    can_view_all_records = db.Column(db.Boolean, default=False)
    profile_photo = db.Column(db.String(200), default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ScheduleEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    location = db.Column(db.String(200), default='1436 Deerfield RD')
    event_type = db.Column(db.String(50), default='Church Service')
    is_auto = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    signups = db.relationship('ShiftSignUp', backref='event', cascade='all, delete-orphan', lazy=True)

class ShiftSignUp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('schedule_event.id'), nullable=False)
    person_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50))
    service = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PersonOfInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    aliases = db.Column(db.String(200))
    classification = db.Column(db.String(20), default='medium')
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    photo_filename = db.Column(db.String(200))
    license_plate = db.Column(db.String(30), default='')
    vehicle_color = db.Column(db.String(50), default='')
    vehicle_make_model = db.Column(db.String(100), default='')
    last_seen = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author_name = db.Column(db.String(120))
    attachment_filename = db.Column(db.String(200), default=None)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author = db.relationship('User', backref='messages')
    replies = db.relationship('MessageReply', backref='message', cascade='all, delete-orphan', lazy=True)

class MessageReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author = db.relationship('User')

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author_name = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author = db.relationship('User', backref='chat_messages')

class RecordFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_name = db.Column(db.String(200))
    folder = db.Column(db.String(100), default='General')
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='records')

class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='push_subscriptions')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== HELPERS ====================
def ensure_upcoming_sundays(weeks_ahead=52):
    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7
    next_sunday = today + timedelta(days=days_until_sunday)
    for i in range(weeks_ahead):
        sunday = next_sunday + timedelta(weeks=i)
        exists = ScheduleEvent.query.filter(
            ScheduleEvent.event_date == sunday,
            ScheduleEvent.title == 'Church Service'
        ).first()
        if not exists:
            event = ScheduleEvent(
                title='Church Service',
                event_date=sunday,
                start_time='09:30',
                end_time='12:00',
                location='1436 Deerfield RD',
                event_type='Church Service',
                is_auto=True
            )
            db.session.add(event)
    db.session.commit()

# ==================== AUTH ====================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not current_user.check_password(current):
            flash('Current password is incorrect', 'danger')
            return redirect(url_for('change_password'))
        if new != confirm:
            flash('New passwords do not match', 'danger')
            return redirect(url_for('change_password'))
        if len(new) < 6:
            flash('Password must be at least 6 characters', 'danger')
            return redirect(url_for('change_password'))
        current_user.set_password(new)
        db.session.commit()
        flash('Password updated', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# ==================== PROFILE ====================
@app.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.id != user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('dashboard'))
    files = RecordFile.query.filter_by(user_id=user.id).order_by(RecordFile.uploaded_at.desc()).all()
    return render_template('profile.html', user=user, files=files)

@app.route('/profile/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def profile_edit(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.id != user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        if new_username and new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                flash('That username is already taken', 'danger')
                return redirect(url_for('profile_edit', user_id=user.id))
            user.username = new_username
        user.full_name = request.form.get('full_name', user.full_name).strip()
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                if user.profile_photo:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_photo)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"profile_{user.id}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img = Image.open(file.stream)
                img.thumbnail((400, 400))
                img.save(filepath)
                user.profile_photo = filename
        db.session.commit()
        flash('Profile updated', 'success')
        return redirect(url_for('profile', user_id=user.id))
    return render_template('profile_edit.html', user=user)

# ==================== DASHBOARD ====================
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    ensure_upcoming_sundays()
    q = request.args.get('q', '').strip()
    search_pois = []
    search_msgs = []
    if q:
        search_pois = PersonOfInterest.query.filter(
            db.or_(
                PersonOfInterest.name.ilike(f'%{q}%'),
                PersonOfInterest.aliases.ilike(f'%{q}%'),
                PersonOfInterest.description.ilike(f'%{q}%')
            )
        ).limit(10).all()
        search_msgs = Message.query.filter(
            db.or_(
                Message.title.ilike(f'%{q}%'),
                Message.content.ilike(f'%{q}%')
            )
        ).limit(10).all()
    recent_chats = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(5).all()
    today = date.today()
    two_weeks = today + timedelta(days=14)
    upcoming = ScheduleEvent.query.filter(
        ScheduleEvent.event_date >= today,
        ScheduleEvent.event_date <= two_weeks
    ).order_by(ScheduleEvent.event_date).all()
    high_pois = PersonOfInterest.query.filter(
        PersonOfInterest.classification.in_(['critical', 'high'])
    ).order_by(PersonOfInterest.classification).limit(5).all()
    users_by_name = {u.full_name: u for u in User.query.all()}
    return render_template('dashboard.html',
                           q=q,
                           search_pois=search_pois,
                           search_msgs=search_msgs,
                           recent_chats=recent_chats,
                           upcoming=upcoming,
                           high_pois=high_pois,
                           users_by_name=users_by_name,
                           to_eastern=to_eastern)

# ==================== SCHEDULE ====================
@app.route('/schedule')
@app.route('/schedule/<int:year>/<int:month>')
@login_required
def schedule(year=None, month=None):
    ensure_upcoming_sundays()
    today = date.today()
    if year is None or month is None:
        year, month = today.year, today.month
    first = date(year, month, 1)
    import datetime as dt
    weeks = []
    current = first
    while current.weekday() != 6:
        current -= dt.timedelta(days=1)
    for _ in range(6):
        week = []
        for _ in range(7):
            if current.month == month:
                week.append(current.day)
            else:
                week.append(0)
            current += dt.timedelta(days=1)
        weeks.append(week)
        if current.month != month and current.weekday() == 6:
            break
    events = ScheduleEvent.query.filter(
        db.extract('year', ScheduleEvent.event_date) == year,
        db.extract('month', ScheduleEvent.event_date) == month
    ).order_by(ScheduleEvent.event_date).all()
    events_by_day = {}
    for e in events:
        events_by_day.setdefault(e.event_date.day, []).append(e)
    prev_month = first - relativedelta(months=1)
    next_m = first + relativedelta(months=1)
    users_by_name = {u.full_name: u for u in User.query.all()}
    return render_template('schedule.html',
                           year=year, month=month, weeks=weeks,
                           events_by_day=events_by_day, first=first,
                           prev_year=prev_month.year, prev_month=prev_month.month,
                           next_year=next_m.year, next_month=next_m.month,
                           month_name=first.strftime('%B'),
                           users_by_name=users_by_name)

@app.route('/schedule/add', methods=['GET', 'POST'])
@login_required
def schedule_add_event():
    default_date = request.args.get('date', '')
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        event_date_str = request.form.get('event_date')
        event_type = request.form.get('event_type', 'Special Event')
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None
        location = request.form.get('location', '').strip() or '1436 Deerfield RD'
        if not title or not event_date_str:
            flash('Title and date required', 'danger')
            return redirect(url_for('schedule_add_event'))
        event = ScheduleEvent(
            title=title,
            event_date=datetime.strptime(event_date_str, '%Y-%m-%d').date(),
            start_time=start_time,
            end_time=end_time,
            location=location,
            event_type=event_type,
            is_auto=False
        )
        db.session.add(event)
        db.session.commit()
        flash('Event created', 'success')
        return redirect(url_for('schedule_detail', event_id=event.id))
    return render_template('schedule_add_event.html', default_date=default_date)

@app.route('/schedule/<int:event_id>')
@login_required
def schedule_detail(event_id):
    event = ScheduleEvent.query.get_or_404(event_id)
    safety_users = User.query.filter_by(is_safety_team=True).order_by(User.full_name).all()
    return render_template('schedule_detail.html', event=event, safety_users=safety_users)

@app.route('/schedule/<int:event_id>/signup', methods=['POST'])
@login_required
def schedule_signup(event_id):
    event = ScheduleEvent.query.get_or_404(event_id)
    person_name = request.form.get('person_name', '').strip()
    role = request.form.get('role', '')
    service = request.form.get('service', '')
    if not person_name:
        flash('Name required', 'danger')
        return redirect(url_for('schedule_detail', event_id=event_id))
    signup = ShiftSignUp(event_id=event.id, person_name=person_name, role=role, service=service)
    db.session.add(signup)
    db.session.commit()
    flash('Signed up', 'success')
    return redirect(url_for('schedule_detail', event_id=event_id))

@app.route('/schedule/signup/<int:signup_id>/delete', methods=['POST'])
@login_required
def schedule_signup_delete(signup_id):
    signup = ShiftSignUp.query.get_or_404(signup_id)
    event_id = signup.event_id
    db.session.delete(signup)
    db.session.commit()
    flash('Removed', 'success')
    return redirect(url_for('schedule_detail', event_id=event_id))

@app.route('/schedule/<int:event_id>/delete', methods=['POST'])
@login_required
def schedule_delete(event_id):
    event = ScheduleEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted', 'success')
    return redirect(url_for('schedule'))

# ==================== USERS ====================
@app.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    all_users = User.query.order_by(User.full_name).all()
    return render_template('users.html', users=all_users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def user_add():
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'member')
        is_safety_team = 'is_safety_team' in request.form
        can_view_all_records = 'can_view_all_records' in request.form
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('user_add'))
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_safety_team=is_safety_team,
            can_view_all_records=can_view_all_records
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'User {username} created', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=None)

@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.full_name = request.form.get('full_name', user.full_name).strip()
        user.role = request.form.get('role', user.role)
        user.is_safety_team = 'is_safety_team' in request.form
        user.can_view_all_records = 'can_view_all_records' in request.form
        new_password = request.form.get('password', '').strip()
        if new_password:
            user.set_password(new_password)
        db.session.commit()
        flash('User updated', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=user)

@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def user_delete(user_id):
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    if user_id == current_user.id:
        flash('Cannot delete yourself', 'danger')
        return redirect(url_for('users'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'success')
    return redirect(url_for('users'))

# ==================== RECORDS ====================
@app.route('/records')
@login_required
def records():
    if not (current_user.role == 'admin' or current_user.can_view_all_records):
        return redirect(url_for('profile', user_id=current_user.id))
    users = User.query.order_by(User.full_name).all()
    return render_template('records.html', users=users)

@app.route('/records/<int:user_id>')
@login_required
def records_user(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.id != user.id and not (current_user.role == 'admin' or current_user.can_view_all_records):
        flash('You do not have permission to view these records', 'danger')
        return redirect(url_for('profile', user_id=current_user.id))
    files = RecordFile.query.filter_by(user_id=user_id).order_by(RecordFile.uploaded_at.desc()).all()
    return render_template('records_user.html', user=user, files=files)

@app.route('/records/<int:user_id>/upload', methods=['POST'])
@login_required
def records_upload(user_id):
    if 'file' not in request.files:
        flash('No file', 'danger')
        return redirect(url_for('records_user', user_id=user_id))
    file = request.files['file']
    folder = request.form.get('folder', 'General').strip() or 'General'
    if file and file.filename:
        original = secure_filename(file.filename)
        ext = original.rsplit('.', 1)[-1].lower() if '.' in original else 'bin'
        filename = f"record_{user_id}_{uuid.uuid4().hex[:10]}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        rec = RecordFile(user_id=user_id, filename=filename, original_name=original, folder=folder)
        db.session.add(rec)
        db.session.commit()
        flash('File uploaded', 'success')
    return redirect(url_for('records_user', user_id=user_id))

@app.route('/records/delete/<int:file_id>', methods=['POST'])
@login_required
def records_delete(file_id):
    rec = RecordFile.query.get_or_404(file_id)
    user_id = rec.user_id
    path = os.path.join(app.config['UPLOAD_FOLDER'], rec.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(rec)
    db.session.commit()
    flash('File deleted', 'success')
    return redirect(url_for('records_user', user_id=user_id))

# ==================== POI ====================
@app.route('/poi')
@login_required
def poi_list():
    q = request.args.get('q', '').strip()
    classification = request.args.get('classification', '')
    query = PersonOfInterest.query
    if q:
        query = query.filter(db.or_(
            PersonOfInterest.name.ilike(f'%{q}%'),
            PersonOfInterest.aliases.ilike(f'%{q}%'),
            PersonOfInterest.description.ilike(f'%{q}%')
        ))
    if classification:
        query = query.filter_by(classification=classification)
    pois = query.order_by(PersonOfInterest.name).all()
    return render_template('poi_list.html', pois=pois, q=q, classification=classification)

@app.route('/poi/add', methods=['GET', 'POST'])
@login_required
def poi_add():
    if request.method == 'POST':
        poi = PersonOfInterest(
            name=request.form.get('name', '').strip(),
            aliases=request.form.get('aliases', '').strip(),
            classification=request.form.get('classification', 'medium'),
            description=request.form.get('description', ''),
            notes=request.form.get('notes', ''),
            license_plate=request.form.get('license_plate', ''),
            vehicle_color=request.form.get('vehicle_color', ''),
            vehicle_make_model=request.form.get('vehicle_make_model', '')
        )
        last_seen = request.form.get('last_seen')
        if last_seen:
            poi.last_seen = datetime.strptime(last_seen, '%Y-%m-%d').date()
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"poi_{uuid.uuid4().hex[:10]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img = Image.open(file.stream)
                img.thumbnail((800, 800))
                img.save(filepath)
                poi.photo_filename = filename
        db.session.add(poi)
        db.session.commit()
        flash('POI added', 'success')
        return redirect(url_for('poi_detail', poi_id=poi.id))
    return render_template('poi_form.html', poi=None)

@app.route('/poi/<int:poi_id>')
@login_required
def poi_detail(poi_id):
    poi = PersonOfInterest.query.get_or_404(poi_id)
    return render_template('poi_detail.html', poi=poi)

@app.route('/poi/<int:poi_id>/edit', methods=['GET', 'POST'])
@login_required
def poi_edit(poi_id):
    poi = PersonOfInterest.query.get_or_404(poi_id)
    if request.method == 'POST':
        poi.name = request.form.get('name', '').strip()
        poi.aliases = request.form.get('aliases', '').strip()
        poi.classification = request.form.get('classification', 'medium')
        poi.description = request.form.get('description', '')
        poi.notes = request.form.get('notes', '')
        poi.license_plate = request.form.get('license_plate', '')
        poi.vehicle_color = request.form.get('vehicle_color', '')
        poi.vehicle_make_model = request.form.get('vehicle_make_model', '')
        last_seen = request.form.get('last_seen')
        poi.last_seen = datetime.strptime(last_seen, '%Y-%m-%d').date() if last_seen else None
        poi.updated_at = datetime.utcnow()
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                if poi.photo_filename:
                    old = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
                    if os.path.exists(old):
                        os.remove(old)
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"poi_{uuid.uuid4().hex[:10]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img = Image.open(file.stream)
                img.thumbnail((800, 800))
                img.save(filepath)
                poi.photo_filename = filename
        db.session.commit()
        flash('POI updated', 'success')
        return redirect(url_for('poi_detail', poi_id=poi.id))
    return render_template('poi_form.html', poi=poi)

@app.route('/poi/<int:poi_id>/delete', methods=['POST'])
@login_required
def poi_delete(poi_id):
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('poi_list'))
    poi = PersonOfInterest.query.get_or_404(poi_id)
    if poi.photo_filename:
        path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(poi)
    db.session.commit()
    flash('POI deleted', 'success')
    return redirect(url_for('poi_list'))

# ===== PDF EXPORT =====
@app.route('/poi/<int:poi_id>/export-pdf')
@login_required
def poi_export_pdf(poi_id):
    poi = PersonOfInterest.query.get_or_404(poi_id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, spaceAfter=12, textColor='#111111')
    label_style = ParagraphStyle('LabelStyle', parent=styles['Normal'], fontSize=10, textColor='#333333', spaceAfter=2)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=10, leading=14, spaceAfter=8)
    elements = []
    elements.append(Paragraph(f"Person of Interest: {poi.name}", title_style))
    elements.append(Spacer(1, 8))
    if poi.photo_filename:
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
        if os.path.exists(photo_path):
            try:
                img = RLImage(photo_path, width=2.2*inch, height=2.2*inch)
                elements.append(img)
                elements.append(Spacer(1, 10))
            except:
                pass
    elements.append(Paragraph(f"<b>Classification:</b> {poi.classification.upper()}", normal_style))
    if poi.aliases:
        elements.append(Paragraph(f"<b>Aliases:</b> {poi.aliases}", normal_style))
    if poi.last_seen:
        elements.append(Paragraph(f"<b>Last Seen:</b> {poi.last_seen.strftime('%Y-%m-%d')}", normal_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("<b>Description / Appearance</b>", label_style))
    elements.append(Paragraph(poi.description or "—", normal_style))
    if poi.license_plate or poi.vehicle_color or poi.vehicle_make_model:
        elements.append(Paragraph("<b>Vehicle Information</b>", label_style))
        vehicle_text = []
        if poi.vehicle_color:
            vehicle_text.append(f"Color: {poi.vehicle_color}")
        if poi.vehicle_make_model:
            vehicle_text.append(f"Make/Model: {poi.vehicle_make_model}")
        if poi.license_plate:
            vehicle_text.append(f"Plate: {poi.license_plate}")
        elements.append(Paragraph(" | ".join(vehicle_text), normal_style))
    if poi.notes:
        elements.append(Paragraph("<b>Internal Notes</b>", label_style))
        elements.append(Paragraph(poi.notes, normal_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                              ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor='#666666')))
    doc.build(elements)
    buffer.seek(0)
    filename = f"POI_{poi.name.replace(' ', '_')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/poi/export-all-pdf')
@login_required
def poi_export_all_pdf():
    pois = PersonOfInterest.query.order_by(PersonOfInterest.classification.desc(), PersonOfInterest.name).all()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=14, spaceAfter=10)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontSize=12, spaceBefore=12, spaceAfter=6)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=9, leading=12, spaceAfter=4)
    elements = []
    elements.append(Paragraph("CNAZ Safety – Persons of Interest", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Total: {len(pois)}", normal_style))
    elements.append(Spacer(1, 10))
    for poi in pois:
        elements.append(Paragraph(f"{poi.name}  ({poi.classification.upper()})", heading_style))
        if poi.photo_filename:
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
            if os.path.exists(photo_path):
                try:
                    img = RLImage(photo_path, width=1.6*inch, height=1.6*inch)
                    elements.append(img)
                    elements.append(Spacer(1, 6))
                except:
                    pass
        if poi.aliases:
            elements.append(Paragraph(f"<b>Aliases:</b> {poi.aliases}", normal_style))
        elements.append(Paragraph(f"<b>Description / Appearance:</b> {poi.description or '—'}", normal_style))
        if poi.license_plate or poi.vehicle_color or poi.vehicle_make_model:
            vehicle = []
            if poi.vehicle_color: vehicle.append(poi.vehicle_color)
            if poi.vehicle_make_model: vehicle.append(poi.vehicle_make_model)
            if poi.license_plate: vehicle.append(f"Plate: {poi.license_plate}")
            elements.append(Paragraph(f"<b>Vehicle:</b> {' | '.join(vehicle)}", normal_style))
        if poi.notes:
            elements.append(Paragraph(f"<b>Notes:</b> {poi.notes}", normal_style))
        elements.append(Spacer(1, 8))
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="CNAZ_All_POIs.pdf", mimetype='application/pdf')

# ==================== MESSAGE BOARD ====================
@app.route('/messages')
@login_required
def messages():
    msgs = Message.query.order_by(Message.is_pinned.desc(), Message.created_at.desc()).all()
    return render_template('messages.html', messages=msgs)

@app.route('/messages/add', methods=['GET', 'POST'])
@login_required
def message_add():
    if request.method == 'POST':
        msg = Message(
            title=request.form.get('title', '').strip(),
            content=request.form.get('content', ''),
            author_id=current_user.id,
            author_name=current_user.full_name,
            is_pinned='is_pinned' in request.form
        )
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"msg_{uuid.uuid4().hex[:10]}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                msg.attachment_filename = filename
        db.session.add(msg)
        db.session.commit()
        flash('Posted', 'success')
        return redirect(url_for('messages'))
    return render_template('message_form.html', msg=None)

@app.route('/messages/<int:msg_id>')
@login_required
def message_detail(msg_id):
    msg = Message.query.get_or_404(msg_id)
    return render_template('message_detail.html', msg=msg, to_eastern=to_eastern)

@app.route('/messages/<int:msg_id>/edit', methods=['GET', 'POST'])
@login_required
def message_edit(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.author_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('messages'))
    if request.method == 'POST':
        msg.title = request.form.get('title', '').strip()
        msg.content = request.form.get('content', '')
        msg.is_pinned = 'is_pinned' in request.form
        msg.updated_at = datetime.utcnow()
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                if msg.attachment_filename:
                    old = os.path.join(app.config['UPLOAD_FOLDER'], msg.attachment_filename)
                    if os.path.exists(old):
                        os.remove(old)
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"msg_{uuid.uuid4().hex[:10]}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                msg.attachment_filename = filename
        db.session.commit()
        flash('Updated', 'success')
        return redirect(url_for('message_detail', msg_id=msg.id))
    return render_template('message_form.html', msg=msg)

@app.route('/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def message_delete(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.author_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('messages'))
    if msg.attachment_filename:
        path = os.path.join(app.config['UPLOAD_FOLDER'], msg.attachment_filename)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(msg)
    db.session.commit()
    flash('Deleted', 'success')
    return redirect(url_for('messages'))

@app.route('/messages/<int:msg_id>/reply', methods=['POST'])
@login_required
def message_reply(msg_id):
    msg = Message.query.get_or_404(msg_id)
    content = request.form.get('content', '').strip()
    if content:
        reply = MessageReply(message_id=msg.id, content=content, author_id=current_user.id)
        db.session.add(reply)
        db.session.commit()
        flash('Reply added', 'success')
    return redirect(url_for('message_detail', msg_id=msg_id))

# ==================== GROUP CHAT ====================
@app.route('/chat')
@login_required
def chat():
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(100).all()
    users_by_name = {u.full_name: u for u in User.query.all()}
    return render_template('chat.html', messages=messages, users_by_name=users_by_name)

@app.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    content = request.form.get('content', '').strip()
    if content:
        msg = ChatMessage(
            content=content,
            author_id=current_user.id,
            author_name=current_user.full_name
        )
        db.session.add(msg)
        db.session.commit()

        # Send push notifications
        try:
            subscriptions = PushSubscription.query.filter(
                PushSubscription.user_id != current_user.id
            ).all()

            payload = json.dumps({
                'title': 'CNAZ Safety Chat',
                'body': f'{current_user.full_name}: {content[:80]}',
                'url': '/chat'
            })

            vapid_private = os.environ.get('VAPID_PRIVATE_KEY')
            for sub in subscriptions:
                try:
                    webpush(
                        subscription_info={
                            'endpoint': sub.endpoint,
                            'keys': {
                                'p256dh': sub.p256dh,
                                'auth': sub.auth
                            }
                        },
                        data=payload,
                        vapid_private_key=vapid_private,
                        vapid_claims={'sub': 'mailto:admin@cnazsafety.local'}
                    )
                except WebPushException as e:
                    if e.response and e.response.status_code in [404, 410]:
                        db.session.delete(sub)
                        db.session.commit()
        except Exception as e:
            print('Push error:', e)

    return redirect(url_for('chat'))

@app.route('/chat/<int:msg_id>/edit', methods=['GET', 'POST'])
@login_required
def chat_edit(msg_id):
    msg = ChatMessage.query.get_or_404(msg_id)
    if msg.author_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('chat'))
    if request.method == 'POST':
        msg.content = request.form.get('content', '').strip()
        msg.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Updated', 'success')
        return redirect(url_for('chat'))
    return render_template('chat_edit.html', message=msg)

@app.route('/chat/<int:msg_id>/delete', methods=['POST'])
@login_required
def chat_delete(msg_id):
    msg = ChatMessage.query.get_or_404(msg_id)
    if msg.author_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed', 'danger')
        return redirect(url_for('chat'))
    db.session.delete(msg)
    db.session.commit()
    flash('Deleted', 'success')
    return redirect(url_for('chat'))

# ==================== PUSH SUBSCRIBE ====================
@app.route('/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    data = request.get_json()
    if not data or 'endpoint' not in data:
        return jsonify({'success': False}), 400
    existing = PushSubscription.query.filter_by(
        user_id=current_user.id,
        endpoint=data['endpoint']
    ).first()
    if existing:
        db.session.delete(existing)
    sub = PushSubscription(
        user_id=current_user.id,
        endpoint=data['endpoint'],
        p256dh=data['keys']['p256dh'],
        auth=data['keys']['auth']
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/push/unsubscribe', methods=['POST'])
@login_required
def push_unsubscribe():
    data = request.get_json()
    if data and 'endpoint' in data:
        sub = PushSubscription.query.filter_by(
            user_id=current_user.id,
            endpoint=data['endpoint']
        ).first()
        if sub:
            db.session.delete(sub)
            db.session.commit()
    return jsonify({'success': True})

# ==================== INIT ====================
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', full_name='System Admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
