import os
import sqlite3
from flask import Flask, render_template, jsonify, request, send_file, session
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import scraper
import re
import json

APP_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(APP_DIR, 'data.db')

ADMIN_PASSWORD = os.environ.get('WEBMAIL_ADMIN_PWD', 'change_this_admin_pwd')

app = Flask(__name__)
app.secret_key = os.environ.get('WEBMAIL_SECRET') or os.environ.get('SECRET_KEY') or 'change_this_secret_key'

def is_admin_authenticated(pwd=None):
    # session-based auth preferred
    try:
        if session.get('is_admin'):
            return True
    except Exception:
        pass
    if pwd and pwd == ADMIN_PASSWORD:
        return True
    return False

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id TEXT UNIQUE,
        subject TEXT,
        sender TEXT,
        date TEXT,
        snippet TEXT,
        category TEXT,
        assigned_to TEXT,
        status TEXT,
        priority INTEGER DEFAULT 0,
        scraped_at TEXT,
        applied_class TEXT
    )
    ''')
    conn.commit()
    # assignment change log
    cur.execute('''
    CREATE TABLE IF NOT EXISTS assignment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id INTEGER,
        old_assigned TEXT,
        new_assigned TEXT,
        user TEXT,
        changed_at TEXT
    )
    ''')
    conn.commit()
    # ensure `priority` and `applied_class` columns exist for older DBs
    cur2 = conn.cursor()
    cur2.execute("PRAGMA table_info(emails)")
    cols = [r[1] for r in cur2.fetchall()]
    if 'priority' not in cols:
        try:
            cur2.execute('ALTER TABLE emails ADD COLUMN priority INTEGER DEFAULT 0')
            conn.commit()
        except Exception:
            pass
    if 'applied_class' not in cols:
        try:
            cur2.execute('ALTER TABLE emails ADD COLUMN applied_class TEXT')
            conn.commit()
        except Exception:
            pass
    conn.close()

def save_emails(items):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for it in items:
        try:
            cur.execute('''INSERT OR REPLACE INTO emails (msg_id, subject, sender, date, snippet, category, assigned_to, status, priority, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                it.get('msg_id'), it.get('subject'), it.get('sender'), it.get('date'), it.get('snippet'), it.get('category'), it.get('assigned_to'), it.get('status', 'Pending'), int(bool(it.get('priority'))), datetime.utcnow().isoformat()
            ))
        except Exception:
            pass
    conn.commit()
    conn.close()

def get_all_emails():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, msg_id, subject, sender, date, snippet, category, assigned_to, status, priority, scraped_at, applied_class FROM emails ORDER BY date DESC')
    rows = cur.fetchall()
    conn.close()
    keys = ['id','msg_id','subject','sender','date','snippet','category','assigned_to','status','priority','scraped_at','applied_class']
    items = [dict(zip(keys, r)) for r in rows]
    # attach display_class based on server-side priority rules
    rules_path = os.path.join(APP_DIR, 'priority_rules.json')
    try:
        with open(rules_path, 'r') as f:
            rules = json.load(f)
    except Exception:
        rules = []
    # compile regexes
    compiled = []
    for r in rules:
        try:
            compiled.append({'pattern': re.compile(r.get('pattern',''), re.IGNORECASE), 'class': r.get('class')})
        except Exception:
            pass
    for it in items:
        it['display_class'] = None
        txt = ' '.join([str(it.get('sender') or ''), str(it.get('subject') or ''), str(it.get('category') or '')])
        for c in compiled:
            try:
                if c['pattern'].search(txt):
                    it['display_class'] = c['class']
                    break
            except Exception:
                continue
    return items


@app.route('/api/priority_rules', methods=['GET','POST'])
def api_priority_rules():
    rules_path = os.path.join(APP_DIR, 'priority_rules.json')
    if request.method == 'GET':
        try:
            with open(rules_path,'r') as f:
                return jsonify(json.load(f))
        except Exception:
            return jsonify([])
    # POST -> update rules (admin only)
    payload = request.json or {}
    pwd = payload.get('admin_pwd')
    if not is_admin_authenticated(pwd):
        return jsonify({'error':'admin password required'}), 403
    rules = payload.get('rules')
    try:
        with open(rules_path,'w') as f:
            json.dump(rules, f, indent=2)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def compute_rule_counts(rules):
    # returns list of dicts {name, class, pattern, count}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT subject,sender,category FROM emails')
    rows = cur.fetchall()
    conn.close()
    compiled = []
    for r in rules:
        try:
            compiled.append({'name': r.get('name'), 'class': r.get('class'), 'pattern': r.get('pattern'), 're': re.compile(r.get('pattern',''), re.IGNORECASE), 'count': 0})
        except Exception:
            compiled.append({'name': r.get('name'), 'class': r.get('class'), 'pattern': r.get('pattern'), 're': None, 'count': 0})
    for row in rows:
        txt = ' '.join([str(row[1] or ''), str(row[0] or ''), str(row[2] or '')])
        matched = False
        for c in compiled:
            try:
                if c['re'] and c['re'].search(txt):
                    c['count'] += 1
                    matched = True
                    break
            except Exception:
                continue
        if not matched and compiled:
            # optional: allocate to last rule (fallback)
            compiled[-1]['count'] += 1
    return [{k: c[k] for k in ('name','class','pattern','count')} for c in compiled]


def apply_rules_to_db(rules):
    # compile rules
    compiled = []
    for r in rules:
        try:
            compiled.append({'class': r.get('class'), 're': re.compile(r.get('pattern',''), re.IGNORECASE)})
        except Exception:
            compiled.append({'class': r.get('class'), 're': None})
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, subject, sender, category FROM emails')
    rows = cur.fetchall()
    updated = 0
    # classes for which we automatically mark priority=1
    priority_classes = set(['priority-additional','priority-citaitatprccc','priority-citoffice'])
    for row in rows:
        eid = row[0]
        txt = ' '.join([str(row[2] or ''), str(row[1] or ''), str(row[3] or '')])
        applied = None
        for c in compiled:
            try:
                if c['re'] and c['re'].search(txt):
                    applied = c['class']
                    break
            except Exception:
                continue
        if applied is None and compiled:
            applied = compiled[-1]['class']
        # set priority flag for certain classes
        pri_flag = 1 if (applied in priority_classes) else 0
        try:
            cur.execute('UPDATE emails SET applied_class=?, priority=? WHERE id=?', (applied, pri_flag, eid))
            updated += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return updated


@app.route('/api/priority_rules/preview', methods=['GET','POST'])
def api_priority_rules_preview():
    # GET returns preview of current rules; POST with JSON body {rules: [...]} previews provided rules
    if request.method == 'GET':
        rules_path = os.path.join(APP_DIR, 'priority_rules.json')
        try:
            with open(rules_path,'r') as f:
                rules = json.load(f)
        except Exception:
            rules = []
    else:
        payload = request.json or {}
        rules = payload.get('rules') or []
    counts = compute_rule_counts(rules)
    return jsonify(counts)


@app.route('/api/priority_rules/apply', methods=['POST'])
def api_priority_rules_apply():
    payload = request.json or {}
    pwd = payload.get('admin_pwd')
    if not is_admin_authenticated(pwd):
        return jsonify({'error':'admin password required'}), 403
    rules = payload.get('rules')
    if not isinstance(rules, list):
        return jsonify({'error':'rules must be an array'}), 400
    # write rules to disk
    rules_path = os.path.join(APP_DIR, 'priority_rules.json')
    try:
        with open(rules_path,'w') as f:
            json.dump(rules, f, indent=2)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    # apply to DB
    updated = apply_rules_to_db(rules)
    counts = compute_rule_counts(rules)
    return jsonify({'ok': True, 'updated': updated, 'counts': counts})

@app.route('/')
def index():
    staff = []
    try:
        staff = scraper.parse_workorder()
    except Exception:
        staff = []
    return render_template('dashboard.html', staff=staff)

@app.route('/api/emails')
def api_emails():
    return jsonify(get_all_emails())


@app.route('/api/check_admin', methods=['POST'])
def api_check_admin():
    payload = request.json or {}
    pwd = payload.get('pwd')
    # allow session-based admin or direct pwd
    if is_admin_authenticated(pwd):
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 403


@app.route('/api/login_admin', methods=['POST'])
def api_login_admin():
    payload = request.json or {}
    pwd = payload.get('pwd')
    if pwd and pwd == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 403


@app.route('/api/logout_admin', methods=['POST'])
def api_logout_admin():
    try:
        session.pop('is_admin', None)
    except Exception:
        pass
    return jsonify({'ok': True})


@app.route('/api/admin_status')
def api_admin_status():
    return jsonify({'is_admin': bool(session.get('is_admin'))})


@app.route('/export_priority')
def export_priority():
    # Export priority=1 messages as CSV
    import csv
    import io
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, msg_id, subject, sender, date, snippet, category, assigned_to, status, priority, scraped_at FROM emails WHERE priority=1 ORDER BY date DESC")
    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id','msg_id','subject','sender','date','snippet','category','assigned_to','status','priority','scraped_at'])
    for r in rows:
        writer.writerow(r)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='priority_emails.csv')

@app.route('/api/email/<int:eid>', methods=['PATCH'])
def update_email(eid):
    payload = request.json or {}
    # Restrict certain edits to admin only
    admin_action = payload.get('admin_action')
    pwd = payload.get('admin_pwd')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if admin_action:
        if not is_admin_authenticated(pwd):
            conn.close()
            return jsonify({'error':'admin password required'}), 403
        # allowed admin fields: category, assigned_to
        if 'category' in payload:
            cur.execute('UPDATE emails SET category=? WHERE id=?', (payload['category'], eid))
        if 'assigned_to' in payload:
            # log assignment change
            cur.execute('SELECT assigned_to FROM emails WHERE id=?', (eid,))
            row = cur.fetchone()
            old = row[0] if row else None
            cur.execute('UPDATE emails SET assigned_to=? WHERE id=?', (payload['assigned_to'], eid))
            try:
                cur.execute('INSERT INTO assignment_logs (email_id, old_assigned, new_assigned, user, changed_at) VALUES (?, ?, ?, ?, ?)',
                            (eid, old, payload['assigned_to'], 'admin', datetime.utcnow().isoformat()))
            except Exception:
                pass
        if 'priority' in payload:
            try:
                pri = int(payload.get('priority', 0))
            except Exception:
                pri = 0
            cur.execute('UPDATE emails SET priority=? WHERE id=?', (pri, eid))
    else:
        # allow non-admin users to change assignment only (and log it)
        if 'assigned_to' in payload:
            cur.execute('SELECT assigned_to FROM emails WHERE id=?', (eid,))
            row = cur.fetchone()
            old = row[0] if row else None
            cur.execute('UPDATE emails SET assigned_to=? WHERE id=?', (payload['assigned_to'], eid))
            try:
                cur.execute('INSERT INTO assignment_logs (email_id, old_assigned, new_assigned, user, changed_at) VALUES (?, ?, ?, ?, ?)',
                            (eid, old, payload['assigned_to'], 'user', datetime.utcnow().isoformat()))
            except Exception:
                pass
    # status can be updated by any staff user
    if 'status' in payload:
        cur.execute('UPDATE emails SET status=? WHERE id=?', (payload['status'], eid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/email/<int:eid>/priority', methods=['POST'])
def set_priority(eid):
    payload = request.json or {}
    try:
        pri = int(bool(payload.get('priority')))
    except Exception:
        pri = 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE emails SET priority=? WHERE id=?', (pri, eid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/assignment_logs')
def api_assignment_logs():
    limit = int(request.args.get('limit', 50))
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id,email_id,old_assigned,new_assigned,user,changed_at FROM assignment_logs ORDER BY changed_at DESC LIMIT ?', (limit,))
    rows = cur.fetchall()
    conn.close()
    keys = ['id','email_id','old_assigned','new_assigned','user','changed_at']
    return jsonify([dict(zip(keys, r)) for r in rows])

@app.route('/export_static')
def export_static():
    # dump a simple static html snapshot
    emails = get_all_emails()
    out = render_template('dashboard_static.html', emails=emails)
    path = os.path.join(APP_DIR, 'dashboard_snapshot.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(out)
    return send_file(path, as_attachment=True)

def scheduled_job():
    print('Scheduled scrape started at', datetime.now())
    try:
        # Prefer IMAP-based scrape; fall back to web UI if IMAP fails
        items = []
        try:
            items = scraper.imap_scrape_and_prepare(
                username=os.environ.get('WEBMAIL_USER'),
                password=os.environ.get('WEBMAIL_PWD'),
                host=os.environ.get('IMAP_HOST', 'webmail.incometax.gov.in')
            )
            print('IMAP scrape returned', len(items), 'items')
        except Exception as e:
            print('IMAP scrape failed, falling back to web UI:', e)
            items = scraper.scrape_and_prepare(
                username=os.environ.get('WEBMAIL_USER'),
                password=os.environ.get('WEBMAIL_PWD')
            )
        if items:
            save_emails(items)
            print('Saved', len(items), 'items')
    except Exception as e:
        print('Scrape error:', e)

if __name__ == '__main__':
    init_db()
    # run a first scrape on startup (optional)
    # scheduled daily at 10:30 local time
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_job, 'cron', hour=10, minute=30)
    scheduler.start()
    # Host on port 8080 by default
    print('Starting Flask server on http://0.0.0.0:8080')
    app.run(host='0.0.0.0', port=8080)
