# Church Safety Team App

A simple web application for church safety teams with:

- **Username / Password login** (role-based: admin & member)
- **Scheduling Calendar** – monthly view, add/edit/delete events, assign people
- **Persons of Interest** – photo upload, classification levels (low / medium / high / critical), search & filter
- **Message Board** – posts, replies, pin important messages (admin)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

Open http://localhost:5000

**Default login:** `admin` / `admin123`  
**Change this password immediately** after first login (or create a new admin and delete the default).

## Features

### Dashboard
Overview of upcoming schedule items, high-priority POIs, and recent messages.

### Schedule
- Full month calendar (Sunday start)
- Click + on a day or use "Add Event"
- Title, date, times, location, assigned people, notes

### Persons of Interest
- Upload photos (auto-resized)
- Classification badges with color coding
- Search by name, alias, description, notes
- Filter by classification level
- Detail view with full notes

### Message Board
- Create posts
- Threaded replies
- Admins can pin posts
- Authors or admins can delete

### User Management (Admin only)
- Create members or additional admins
- Delete users

## Security Notes

This is a starting point for a private team tool. For production:

1. Change `SECRET_KEY` in `app.py`
2. Use a strong password for the admin account
3. Put behind HTTPS (nginx + Let's Encrypt, or a host like Railway / Render / Fly.io)
4. Consider adding rate limiting and stronger password rules
5. Restrict access (VPN or IP allowlist) if the data is sensitive
6. Regularly back up the SQLite file (`instance/church_safety.db` or the root `church_safety.db`)

## Tech Stack

- Flask + Flask-Login + SQLAlchemy
- SQLite
- Bootstrap 5
- Pillow for image handling

## File Layout

```
church_safety_app/
├── app.py
├── requirements.txt
├── static/
│   ├── css/style.css
│   └── uploads/          # uploaded POI photos
├── templates/
└── instance/             # database (created on first run)
```
