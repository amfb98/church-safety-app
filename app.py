from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
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

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EASTERN = pytz.timezone('US/Eastern')

def to_eastern(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(EASTERN)

@app.context_processor
def inject_eastern():
    return dict(to_eastern=to_eastern)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='member')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class PersonOfInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    aliases = db.Column(db.String(256), default='')
    description = db.Column(db.Text, default='')
    classification = db.Column(db.String(20), default='low')
    photo_filename = db.Column(db.String(256), default='')
    notes = db.Column(db.Text, default='')
    license_plate = db.Column(db.String(30), default='')
    vehicle_color = db.Column(db.String(50), default='')
    vehicle_make_model = db.Column(db.String(100), default='')
    last_seen = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScheduleEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default='')
    event_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10), default='')
    end_time = db.Column(db.String(10), default='')
    assigned_to = db.Column(db.String(256), default='')
    location = db.Column(db.String(120), default='')
    role = db.Column(db.String(50), default='')
    service = db.Column(db.String(20), default='')
    event_type = db.Column(db.String(50), default='Church Service')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ShiftSignUp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('schedule_event.id'), nullable=False)
    person_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), default='')
    service = db.Column(db.String(20), default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship('ScheduleEvent', backref=db.backref('signups', lazy=True, cascade='all, delete-orphan'))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author = db.relationship('User', backref='messages')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_pinned = db.Column(db.Boolean, default=False)

class MessageReply(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author = db.relationship('User')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.relationship('Message', backref=db.backref('replies', lazy=True, cascade='all, delete-orphan'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_photo(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        img = Image.open(file.stream)
        img.thumbnail((800, 800))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(filepath, quality=85)
        return filename
    return None

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    upcoming = ScheduleEvent.query.filter(ScheduleEvent.event_date >= today).order_by(ScheduleEvent.event_date).limit(20).all()
    high_pois = PersonOfInterest.query.filter(PersonOfInterest.classification.in_(['high', 'critical'])).order_by(PersonOfInterest.updated_at.desc()).limit(5).all()
    recent_msgs = Message.query.order_by(Message.is_pinned.desc(), Message.created_at.desc()).limit(5).all()
    return render_template('dashboard.html', upcoming=upcoming, high_pois=high_pois, recent_msgs=recent_msgs)

@app.route('/poi')
@login_required
def poi_list():
    q = request.args.get('q', '').strip()
    classification = request.args.get('classification', '')
    query = PersonOfInterest.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                PersonOfInterest.name.ilike(like),
                PersonOfInterest.aliases.ilike(like),
                PersonOfInterest.description.ilike(like),
                PersonOfInterest.notes.ilike(like),
                PersonOfInterest.license_plate.ilike(like),
                PersonOfInterest.vehicle_make_model.ilike(like),
                PersonOfInterest.vehicle_color.ilike(like)
            )
        )
    if classification:
        query = query.filter_by(classification=classification)
    pois = query.order_by(
        db.case(
            (PersonOfInterest.classification == 'critical', 1),
            (PersonOfInterest.classification == 'high', 2),
            (PersonOfInterest.classification == 'medium', 3),
            else_=4
        ),
        PersonOfInterest.name
    ).all()
    return render_template('poi_list.html', pois=pois, q=q, classification=classification)

@app.route('/poi/add', methods=['GET', 'POST'])
@login_required
def poi_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name is required', 'danger')
            return redirect(url_for('poi_add'))
        photo_filename = ''
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename:
                photo_filename = save_photo(file) or ''
        last_seen = None
        ls = request.form.get('last_seen', '')
        if ls:
            try:
                last_seen = datetime.strptime(ls, '%Y-%m-%d').date()
            except ValueError:
                pass
        poi = PersonOfInterest(
            name=name,
            aliases=request.form.get('aliases', '').strip(),
            description=request.form.get('description', '').strip(),
            classification=request.form.get('classification', 'low'),
            photo_filename=photo_filename,
            notes=request.form.get('notes', '').strip(),
            license_plate=request.form.get('license_plate', '').strip(),
            vehicle_color=request.form.get('vehicle_color', '').strip(),
            vehicle_make_model=request.form.get('vehicle_make_model', '').strip(),
            last_seen=last_seen,
            created_by=current_user.id
        )
        db.session.add(poi)
        db.session.commit()
        flash('Person of Interest added successfully', 'success')
        return redirect(url_for('poi_list'))
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
        poi.description = request.form.get('description', '').strip()
        poi.classification = request.form.get('classification', 'low')
        poi.notes = request.form.get('notes', '').strip()
        poi.license_plate = request.form.get('license_plate', '').strip()
        poi.vehicle_color = request.form.get('vehicle_color', '').strip()
        poi.vehicle_make_model = request.form.get('vehicle_make_model', '').strip()
        ls = request.form.get('last_seen', '')
        if ls:
            try:
                poi.last_seen = datetime.strptime(ls, '%Y-%m-%d').date()
            except ValueError:
                poi.last_seen = None
        else:
            poi.last_seen = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename:
                new_photo = save_photo(file)
                if new_photo:
                    if poi.photo_filename:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
                        if os.path.exists(old_path):
                            try:
                                os.remove(old_path)
                            except:
                                pass
                    poi.photo_filename = new_photo
        poi.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Updated successfully', 'success')
        return redirect(url_for('poi_detail', poi_id=poi.id))
    return render_template('poi_form.html', poi=poi)

@app.route('/poi/<int:poi_id>/delete', methods=['POST'])
@login_required
def poi_delete(poi_id):
    if current_user.role != 'admin':
        flash('Only admins can delete', 'danger')
        return redirect(url_for('poi_list'))
    poi = PersonOfInterest.query.get_or_404(poi_id)
    if poi.photo_filename:
        path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
    db.session.delete(poi)
    db.session.commit()
    flash('Deleted', 'success')
    return redirect(url_for('poi_list'))

@app.route('/poi/export/all')
@login_required
def poi_export_all():
    pois = PersonOfInterest.query.order_by(
        db.case(
            (PersonOfInterest.classification == 'critical', 1),
            (PersonOfInterest.classification == 'high', 2),
            (PersonOfInterest.classification == 'medium', 3),
            else_=4
        ),
        PersonOfInterest.name
    ).all()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=12, spaceBefore=14, spaceAfter=4)
    normal = styles['Normal']
    story = []
    story.append(Paragraph("CNAZ Safety – Persons of Interest", title_style))
    story.append(Paragraph(f"Generated: {to_eastern(datetime.utcnow()).strftime('%Y-%m-%d %I:%M %p ET')}", normal))
    story.append(Spacer(1, 16))
    for poi in pois:
        if poi.photo_filename:
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
            if os.path.exists(photo_path):
                try:
                    img = RLImage(photo_path, width=1.5*inch, height=1.5*inch)
                    story.append(img)
                    story.append(Spacer(1, 6))
                except:
                    pass
        story.append(Paragraph(f"<b>{poi.name}</b> [{poi.classification.upper()}]", heading_style))
        if poi.aliases:
            story.append(Paragraph(f"<b>Aliases:</b> {poi.aliases}", normal))
        if poi.description:
            story.append(Paragraph(f"<b>Description:</b> {poi.description}", normal))
        if poi.license_plate or poi.vehicle_color or poi.vehicle_make_model:
            parts = []
            if poi.license_plate: parts.append(f"Plate: {poi.license_plate}")
            if poi.vehicle_color: parts.append(f"Color: {poi.vehicle_color}")
            if poi.vehicle_make_model: parts.append(f"Make/Model: {poi.vehicle_make_model}")
            story.append(Paragraph(f"<b>Vehicle:</b> {' | '.join(parts)}", normal))
        if poi.notes:
            story.append(Paragraph(f"<b>Notes:</b> {poi.notes}", normal))
        if poi.last_seen:
            story.append(Paragraph(f"<b>Last Seen:</b> {poi.last_seen.strftime('%Y-%m-%d')}", normal))
        story.append(Spacer(1, 12))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="CNAZ_POIs_All.pdf", mimetype='application/pdf')

@app.route('/poi/<int:poi_id>/export')
@login_required
def poi_export_one(poi_id):
    poi = PersonOfInterest.query.get_or_404(poi_id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
    normal = styles['Normal']
    story = []
    story.append(Paragraph("CNAZ Safety – Person of Interest", title_style))
    story.append(Spacer(1, 8))
    if poi.photo_filename:
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], poi.photo_filename)
        if os.path.exists(photo_path):
            try:
                img = RLImage(photo_path, width=2.2*inch, height=2.2*inch)
                story.append(img)
                story.append(Spacer(1, 10))
            except:
                pass
    story.append(Paragraph(f"<b>{poi.name}</b> [{poi.classification.upper()}]", styles['Heading2']))
    story.append(Spacer(1, 6))
    if poi.aliases:
        story.append(Paragraph(f"<b>Aliases:</b> {poi.aliases}", normal))
    if poi.description:
        story.append(Paragraph(f"<b>Description:</b> {poi.description}", normal))
    if poi.license_plate or poi.vehicle_color or poi.vehicle_make_model:
        parts = []
        if poi.license_plate: parts.append(f"Plate: {poi.license_plate}")
        if poi.vehicle_color: parts.append(f"Color: {poi.vehicle_color}")
        if poi.vehicle_make_model: parts.append(f"Make/Model: {poi.vehicle_make_model}")
        story.append(Paragraph(f"<b>Vehicle:</b> {' | '.join(parts)}", normal))
    if poi.notes:
        story.append(Paragraph(f"<b>Notes:</b> {poi.notes}", normal))
    if poi.last_seen:
        story.append(Paragraph(f"<b>Last Seen:</b> {poi.last_seen.strftime('%Y-%m-%d')}", normal))
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Generated: {to_eastern(datetime.utcnow()).strftime('%Y-%m-%d %I:%M %p ET')}", normal))
    doc.build(story)
    buffer.seek(0)
    safe_name = "".join(c for c in poi.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    return send_file(buffer, as_attachment=True, download_name=f"POI_{safe_name}.pdf", mimetype='application/pdf')

@app.route('/schedule')
@login_required
def schedule():
    year = request.args.get('year', type=int) or date.today().year
    month = request.args.get('month', type=int) or date.today().month
    if month < 1:
        month = 12
        year -= 1
    if month > 12:
        month = 1
        year += 1

    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    events = ScheduleEvent.query.filter(
        ScheduleEvent.event_date >= first,
        ScheduleEvent.event_date < next_month
    ).order_by(ScheduleEvent.event_date, ScheduleEvent.start_time).all()

    import calendar
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(year, month)
    events_by_day = {}
    for e in events:
        d = e.event_date.day
        if d not in events_by_day:
            events_by_day[d] = []
        events_by_day[d].append(e)

    prev_month = first - relativedelta(months=1)
    next_m = first + relativedelta(months=1)

    return render_template('schedule.html',
                           year=year, month=month, weeks=weeks,
                           events_by_day=events_by_day, first=first,
                           prev_year=prev_month.year, prev_month=prev_month.month,
                           next_year=next_m.year, next_month=next_m.month,
                           month_name=first.strftime('%B'))

@app.route('/schedule/add', methods=['GET', 'POST'])
@login_required
def schedule_add():
    users = User.query.order_by(User.full_name).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        event_date_str = request.form.get('event_date', '')
        event_type = request.form.get('event_type', 'Church Service')
        role = request.form.get('role', '')
        service = request.form.get('service', '')
        location = request.form.get('location', '').strip()
        start_time = request.form.get('start_time', '')
        end_time = request.form.get('end_time', '')

        if not title or not event_date_str:
            flash('Person and date are required', 'danger')
            return redirect(url_for('schedule_add'))

        try:
            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date', 'danger')
            return redirect(url_for('schedule_add'))

        if event_type == 'Church Service':
            location = '1436 Deerfield Rd'
            if service == 'First':
                start_time = '09:30'
                end_time = '10:30'
            elif service == 'Second':
                start_time = '11:00'
                end_time = '12:00'
            elif service == 'Both':
                start_time = '09:30'
                end_time = '12:00'

        event = ScheduleEvent(
            title=title,
            description='',
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            assigned_to='',
            location=location,
            role=role,
            service=service,
            event_type=event_type,
            created_by=current_user.id
        )
        db.session.add(event)
        db.session.commit()
        flash('Signed up successfully', 'success')
        return redirect(url_for('schedule', year=event_date.year, month=event_date.month))

    copy_id = request.args.get('copy', type=int)
    event = None
    default_date = request.args.get('date', date.today().isoformat())
    if copy_id:
        original = ScheduleEvent.query.get(copy_id)
        if original:
            event = original
            default_date = date.today().isoformat()

    return render_template('schedule_form.html', event=event, default_date=default_date, users=users)

@app.route('/schedule/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def schedule_edit(event_id):
    event = ScheduleEvent.query.get_or_404(event_id)
    users = User.query.order_by(User.full_name).all()

    if request.method == 'POST':
        event.title = request.form.get('title', '').strip()
        event.event_type = request.form.get('event_type', 'Church Service')
        event.role = request.form.get('role', '')
        event.service = request.form.get('service', '')
        event.location = request.form.get('location', '').strip()
        event.start_time = request.form.get('start_time', '')
        event.end_time = request.form.get('end_time', '')

        try:
            event.event_date = datetime.strptime(request.form.get('event_date'), '%Y-%m-%d').date()
        except:
            pass

        if event.event_type == 'Church Service':
            event.location = '1436 Deerfield Rd'
            if event.service == 'First':
                event.start_time = '09:30'
                event.end_time = '10:30'
            elif event.service == 'Second':
                event.start_time = '11:00'
                event.end_time = '12:00'
            elif event.service == 'Both':
                event.start_time = '09:30'
                event.end_time = '12:00'

        db.session.commit()
        flash('Updated', 'success')
        return redirect(url_for('schedule', year=event.event_date.year, month=event.event_date.month))

    return render_template('schedule_form.html', event=event, default_date=event.event_date.isoformat(), users=users)

@app.route('/schedule/<int:event_id>/delete', methods=['POST'])
@login_required
def schedule_delete(event_id):
    event = ScheduleEvent.query.get_or_404(event_id)
    year, month = event.event_date.year, event.event_date.month
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted', 'success')
    return redirect(url_for('schedule', year=year, month=month))

@app.route('/messages')
@login_required
def messages():
    msgs = Message.query.order_by(Message.is_pinned.desc(), Message.created_at.desc()).all()
    return render_template('messages.html', messages=msgs)

@app.route('/messages/new', methods=['GET', 'POST'])
@login_required
def message_new():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash('Title and content required', 'danger')
            return redirect(url_for('message_new'))
        msg = Message(title=title, content=content, author_id=current_user.id, is_pinned=bool(request.form.get('is_pinned')) and current_user.role == 'admin')
        db.session.add(msg)
        db.session.commit()
        flash('Posted', 'success')
        return redirect(url_for('message_detail', msg_id=msg.id))
    return render_template('message_form.html', msg=None)

@app.route('/messages/<int:msg_id>')
@login_required
def message_detail(msg_id):
    msg = Message.query.get_or_404(msg_id)
    return render_template('message_detail.html', msg=msg)

@app.route('/messages/<int:msg_id>/reply', methods=['POST'])
@login_required
def message_reply(msg_id):
    msg = Message.query.get_or_404(msg_id)
    content = request.form.get('content', '').strip()
    if content:
        reply = MessageReply(message_id=msg.id, content=content, author_id=current_user.id)
        db.session.add(reply)
        db.session.commit()
        flash('Reply posted', 'success')
    return redirect(url_for('message_detail', msg_id=msg.id))

@app.route('/messages/<int:msg_id>/edit', methods=['GET', 'POST'])
@login_required
def message_edit(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if current_user.role != 'admin' and msg.author_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('message_detail', msg_id=msg.id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash('Title and content required', 'danger')
            return redirect(url_for('message_edit', msg_id=msg.id))
        msg.title = title
        msg.content = content
        db.session.commit()
        flash('Post updated', 'success')
        return redirect(url_for('message_detail', msg_id=msg.id))
    return render_template('message_form.html', msg=msg)

@app.route('/messages/reply/<int:reply_id>/edit', methods=['GET', 'POST'])
@login_required
def reply_edit(reply_id):
    reply = MessageReply.query.get_or_404(reply_id)
    if current_user.role != 'admin' and reply.author_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('message_detail', msg_id=reply.message_id))
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if not content:
            flash('Reply cannot be empty', 'danger')
            return redirect(url_for('reply_edit', reply_id=reply.id))
        reply.content = content
        db.session.commit()
        flash('Reply updated', 'success')
        return redirect(url_for('message_detail', msg_id=reply.message_id))
    return render_template('reply_edit.html', reply=reply)

@app.route('/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def message_delete(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if current_user.role != 'admin' and msg.author_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('messages'))
    db.session.delete(msg)
    db.session.commit()
    flash('Deleted', 'success')
    return redirect(url_for('messages'))

@app.route('/users')
@login_required
def users():
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    all_users = User.query.order_by(User.username).all()
    return render_template('users.html', users=all_users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def user_add():
    if current_user.role != 'admin':
        flash('Admin only', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'member')
        if not username or not password or not full_name:
            flash('All fields required', 'danger')
            return redirect(url_for('user_add'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('user_add'))
        user = User(username=username, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'User {username} created', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html')

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
        flash('Password updated successfully', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', full_name='System Admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
