import os
from datetime import datetime, timedelta
from docx import Document

def parse_workorder(folder=None):
    # Find first .docx in given folder and try to parse staff list
    if folder is None:
        folder = os.path.join(os.path.expanduser('~'), 'Desktop', 'webmail scrapper')
    for fname in os.listdir(folder):
        if fname.lower().endswith('.docx'):
            path = os.path.join(folder, fname)
            doc = Document(path)
            texts = []
            for p in doc.paragraphs:
                t = p.text.strip()
                if t:
                    texts.append(t)
            # naive extraction: lines that look like names (no colon)
            staff = []
            for line in texts:
                # split by hyphen or colon
                if '-' in line:
                    left = line.split('-')[0].strip()
                    staff.append(left)
                elif ':' in line:
                    left = line.split(':')[0].strip()
                    staff.append(left)
                else:
                    # if line is short and alphabetic
                    if len(line.split()) <= 4:
                        staff.append(line)
            staff = [s for s in staff if len(s) > 1]
            if staff:
                return staff
    return []

def categorize(subject, snippet):
    s = (subject or '') + ' ' + (snippet or '')
    s = s.lower()
    # Map to the requested categories
    keywords = {
        'Received from CPC': ['cpc', 'central processing', 'cpc-'],
        'PrCC Office': ['prcc', 'prcc office', 'prcc-'],
        'Additional office': ['additional office', 'addl', 'addlci', 'additional'],
        'Other JAO charges': ['jao', 'jao charges', 'jao-'],
        'CIT Office': ['cit office', 'commissioner of income tax', 'cit-'],
        'ITBA': ['itba', 'it-base', 'itba-'],
        'Miscellaneus': []
    }
    for cat, kws in keywords.items():
        for kw in kws:
            if kw in s:
                return cat
    # default to Miscellaneus when no keyword matches
    return 'Miscellaneus'


def assign_by_subject(subject, snippet, staff_list):
    """Match staff names mentioned in the subject/snippet. Returns staff name or None."""
    txt = ((subject or '') + ' ' + (snippet or '')).lower()
    for s in staff_list:
        if not s:
            continue
        name = s.lower()
        if name in txt:
            return s
        for tok in name.split():
            if tok and tok in txt:
                return s
    return None


def is_pccit_jaipur(sender):
    try:
        s = (sender or '').lower()
    except Exception:
        return False
    return ('pccit' in s) and ('jaipur' in s)


def is_additional_sender(sender):
    """Return True for generic 'Additional' senders (addl/additional) but
    exclude Delhi ADDL CIT IT special-case which is handled by `is_delhi_sender`.
    """
    try:
        s = (sender or '').lower()
    except Exception:
        return False
    if 'addlcitit' in s:
        return False
    # if both tokens 'delhi' and 'addl' present, treat as Delhi special-case
    if 'delhi' in s and 'addl' in s:
        return False
    if 'additional' in s or 'addl' in s:
        return True
    return False


def is_delhi_sender(sender):
    """Return True if sender appears to be the Delhi ADDL CIT IT address.
    Be tolerant of formats like: '"Delhi.addlcitit.1.3" <Delhi.addlcitit.1.3@incometax.gov.in>'
    """
    try:
        s = (sender or '').lower()
    except Exception:
        return False
    # common patterns observed: delhi.addlcitit, addlcitit, addl.citit, addl_citit, addl cit
    if 'addlcitit' in s or 'delhi.addlcitit' in s or 'addl.citit' in s or 'addl cit' in s or 'addl_citit' in s:
        return True
    # tokens fallback: require addl/addl* and cit/citit and delhi presence
    if 'delhi' in s and ('addl' in s or 'addlci' in s) and ('cit' in s or 'citit' in s):
        return True
    # sometimes localpart contains addl and numbers: match addl + digits
    import re
    if re.search(r'addl\w*\d+', s):
        return True
    return False

def age_days(date_str):
    # Expect ISO or common formats; try parsing
    try:
        dt = datetime.fromisoformat(date_str)
    except Exception:
        try:
            dt = datetime.strptime(date_str, '%d-%b-%Y')
        except Exception:
            return None
    return (datetime.utcnow() - dt).days

def scrape_and_prepare(username=None, password=None):
    # This function will attempt to log into the webmail web UI and extract mails
    # NOTE: web UI structures differ. This implementation tries a few common selectors.
    # If it fails, you may need to update selectors in this file.
    from playwright.sync_api import sync_playwright

    if not username or not password:
        raise ValueError('Provide WEBMAIL_USER and WEBMAIL_PWD environment variables')

    items = []
    staff = parse_workorder()
    # If parsed work-order is absent or too short, fall back to deterministic officials order
    if not staff or len(staff) < 2:
        staff = ['Vipin','Sunil','Rajeev','Anil','Hemraj']

    # subject-based assignment uses module-level `assign_by_subject`

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('https://webmail.incometax.gov.in', timeout=60000)
        # Try to fill login form using common names
        selectors = [
            {'user':'input[name="username"]','pwd':'input[name="password"]','btn':'button[type="submit"]'},
            {'user':'input#username','pwd':'input#password','btn':'button.login'},
            {'user':'input[name="user"]','pwd':'input[name="pass"]','btn':'input[type="submit"]'}
        ]
        logged_in = False
        for sel in selectors:
            try:
                if page.query_selector(sel['user']):
                    page.fill(sel['user'], username)
                    page.fill(sel['pwd'], password)
                    page.click(sel['btn'])
                    page.wait_for_load_state('networkidle', timeout=15000)
                    logged_in = True
                    break
            except Exception:
                continue
        if not logged_in:
            browser.close()
            raise RuntimeError('Login failed. Please check selectors or the site structure.')

        # After login, try to find message list rows
        # Common selectors for webmail inbox rows
        row_selectors = ['tr.message', '.message-row', '.message', 'table.mailbox tr']
        rows = []
        for rsel in row_selectors:
            try:
                rows = page.query_selector_all(rsel)
                if rows and len(rows) > 0:
                    break
            except Exception:
                rows = []
        # Fallback: try list items
        if not rows:
            rows = page.query_selector_all('li.mail')

        cutoff = datetime.utcnow() - timedelta(days=60)
        # assign in work-allocation (round-robin) order over the visible rows
        i = 0
        for r in rows:
            try:
                subj = r.query_selector('.subject') and r.query_selector('.subject').inner_text() or r.inner_text()
                sender = r.query_selector('.from') and r.query_selector('.from').inner_text() or ''
                date = r.query_selector('.date') and r.query_selector('.date').inner_text() or ''
                snippet = r.query_selector('.snippet') and r.query_selector('.snippet').inner_text() or ''
                # naive parse of date: attempt iso fallback
                try:
                    dt = datetime.fromisoformat(date)
                except Exception:
                    dt = datetime.utcnow()
                if dt < cutoff:
                    continue
                # special-case: email verification or delivery reports -> Miscellaneus, assign to On File
                lower_txt = ((subj or '') + ' ' + (snippet or '') + ' ' + (sender or '')).lower()
                # If sender/content indicates CPC, ITBA or Mail Delivery System => On File
                if any(kw in lower_txt for kw in ['cpc', 'itba', 'mail delivery', 'maildelivery', 'mail.delivery.system']):
                    cat = 'On File'
                    assigned = 'On File'
                elif any(kw in lower_txt for kw in ['email verification', 'email verification.', 'verification', 'delivery report', 'successful mail delivery', 'delivery-status']):
                    cat = 'Miscellaneus'
                    assigned = 'On File'
                else:
                    # round-robin assignment according to staff order and sender heuristics
                    if is_pccit_jaipur(sender):
                        # PCCIT Jaipur messages should map to PCCIT category
                        cat = 'PCCIT'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    elif is_delhi_sender(sender):
                        # Delhi ADDL CIT IT mails: mark priority and map to Additional office
                        cat = 'Additional office'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    elif is_additional_sender(sender):
                        # Generic Additional office (non-Delhi): map to Additional office but do NOT mark priority
                        cat = 'Additional office'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    else:
                        # try to assign based on subject tokens (work allocation name mentions)
                        matched = assign_by_subject(subj, snippet, staff)
                        if matched:
                            assigned = matched
                            cat = categorize(subj, snippet)
                        elif staff:
                            assigned = staff[i % len(staff)]
                            i += 1
                            cat = categorize(subj, snippet)
                        else:
                            # no staff information: assign to Hemraj and mark Miscellaneus
                            assigned = 'Hemraj'
                            cat = 'Miscellaneus'
                msg_id = subj + '|' + sender + '|' + date
                # priority flag: mails coming from Delhi.addlcitit.1.3. should be flagged
                # priority: only the specific Delhi ADDL CIT IT sender(s) should be flagged
                priority_flag = False
                try:
                    if is_delhi_sender(sender):
                        priority_flag = True
                    # ensure generic 'additional' senders are NOT prioritized
                    if is_additional_sender(sender):
                        priority_flag = False
                except Exception:
                    priority_flag = False
                items.append({
                    'msg_id': msg_id,
                    'subject': subj,
                    'sender': sender,
                    'date': dt.isoformat(),
                    'snippet': snippet,
                    'category': cat,
                    'assigned_to': 'Hemraj' if (cat or '').lower().startswith('miscell') else assigned,
                    'status': 'Pending',
                    'priority': 1 if priority_flag else 0
                })
            except Exception:
                continue

        browser.close()
    return items

def imap_scrape_and_prepare(username, password, host='webmail.incometax.gov.in', port=993, days=60, limit=None):
    """
    Connect to IMAP and fetch messages from the last `days` days.
    Returns a list of item dicts compatible with `save_emails()` in app.py.
    """
    import imaplib, email
    from email.header import decode_header
    from email.utils import parsedate_to_datetime

    if not username or not password:
        raise ValueError('Provide username and password')

    items = []
    staff = parse_workorder()
    # ensure deterministic staff order if parsing failed or returned too few names
    if not staff or len(staff) < 2:
        staff = ['Vipin','Sunil','Rajeev','Anil','Hemraj']

    M = imaplib.IMAP4_SSL(host, port)
    try:
        M.login(username, password)
    except Exception as e:
        M.shutdown()
        raise

    try:
        M.select('INBOX')
        since = (datetime.utcnow() - timedelta(days=days)).strftime('%d-%b-%Y')
        # use UID search for stable identifiers
        typ, data = M.uid('search', None, '(SINCE "{}")'.format(since))
        ids = data[0].split() if data and data[0] else []
        # newest first
        ids = ids[::-1]
        if limit:
            ids = ids[:limit]

        # assign in work allocation order (round-robin) across fetched messages
        i = 0
        for num in ids:
            try:
                # fetch by UID
                typ, msg_parts = M.uid('fetch', num, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)] BODY.PEEK[TEXT])')
                # msg_parts is a list; find header bytes
                header_bytes = b''
                body_bytes = b''
                for part in msg_parts:
                    if isinstance(part, tuple) and part[1]:
                        data = part[1]
                        # crude split: header section contains 'Message-ID' or 'Subject'
                        if b'Message-ID' in data or b'Subject' in data or b'From:' in data:
                            header_bytes += data
                        else:
                            body_bytes += data

                msg = email.message_from_bytes(header_bytes or b'')
                subject_raw = msg.get('Subject', '')
                # decode subject
                subj = ''
                for s, enc in decode_header(subject_raw):
                    if isinstance(s, bytes):
                        subj += s.decode(enc or 'utf-8', errors='ignore')
                    else:
                        subj += s

                sender = msg.get('From', '')
                date_hdr = msg.get('Date', '')
                try:
                    dt = parsedate_to_datetime(date_hdr)
                    date_iso = dt.isoformat()
                except Exception:
                    date_iso = datetime.utcnow().isoformat()

                snippet = ''
                try:
                    # try to extract a small snippet from body_bytes
                    if body_bytes:
                        # decode as utf-8 fallback
                        snippet = body_bytes.decode('utf-8', errors='ignore').strip()[:400]
                except Exception:
                    snippet = ''

                # special-case: email verification or delivery reports -> Miscellaneus, assign to On File
                lower_txt = ((subj or '') + ' ' + (snippet or '') + ' ' + (sender or '')).lower()
                # If sender/content indicates CPC, ITBA or Mail Delivery System => On File
                if any(kw in lower_txt for kw in ['cpc', 'itba', 'mail delivery', 'maildelivery', 'mail.delivery.system']):
                    cat = 'On File'
                    assigned = 'On File'
                elif any(kw in lower_txt for kw in ['email verification', 'email verification.', 'verification', 'delivery report', 'successful mail delivery', 'delivery-status']):
                    cat = 'Miscellaneus'
                    assigned = 'On File'
                else:
                    # round-robin assignment using staff list and sender heuristics
                    if is_pccit_jaipur(sender):
                        cat = 'PCCIT'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    elif is_delhi_sender(sender):
                        cat = 'Additional office'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    elif is_additional_sender(sender):
                        cat = 'Additional office'
                        assigned = staff[i % len(staff)] if staff else 'Hemraj'
                        i += 1
                    else:
                        # try to match subject to staff names first
                        matched = None
                        try:
                            matched = assign_by_subject(subj, snippet, staff)
                        except Exception:
                            matched = None
                        if matched:
                            assigned = matched
                            cat = categorize(subj, snippet)
                        elif staff:
                            assigned = staff[i % len(staff)]
                            i += 1
                            cat = categorize(subj, snippet)
                        else:
                            assigned = 'Hemraj'
                            cat = 'Miscellaneus'

                # Use UID for stable msg_id
                uid = num.decode() if isinstance(num, bytes) else str(num)
                mid = f"{host}:{uid}"

                # priority: only the specific Delhi ADDL CIT IT sender(s) should be flagged
                priority_flag = False
                try:
                    if is_delhi_sender(sender):
                        priority_flag = True
                    if is_additional_sender(sender):
                        # explicit: generic additional senders should NOT be prioritized
                        priority_flag = False
                except Exception:
                    priority_flag = False

                items.append({
                    'msg_id': mid,
                    'subject': subj,
                    'sender': sender,
                    'date': date_iso,
                    'snippet': snippet,
                    'category': cat,
                    'assigned_to': 'Hemraj' if (cat or '').lower().startswith('miscell') else assigned,
                    'status': 'Pending',
                    'priority': 1 if priority_flag else 0
                })
            except Exception:
                continue
    finally:
        try:
            M.logout()
        except Exception:
            pass

    return items


def prefill_assignments_db(db_path=None):
    """
    Pre-fill `assigned_to` in the SQLite DB using work-order round-robin.
    If no work-order docx is found, falls back to default officials order.
    """
    import sqlite3
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), 'data.db')
    # Use fixed officials for prefill to ensure consistent assignment
    staff = ['Vipin','Sunil','Rajeev','Anil','Hemraj']

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # include category column to decide Miscellaneus
    cur.execute('SELECT id, subject, sender, date, category, assigned_to FROM emails ORDER BY date ASC')
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return 0

    i = 0
    updates = 0
    for r in rows:
        eid = r[0]
        subj = r[1] or ''
        snip = r[2] or ''
        category = (r[4] or '')
        lower_txt = (subj + ' ' + snip).lower()
        # If this mail is categorised as Miscellaneus -> assign to Hemraj (except verification/delivery -> On File)
        if (category or '').lower().startswith('miscell'):
            if any(kw in lower_txt for kw in ['email verification', 'verification', 'delivery report', 'mail delivery', 'successful mail delivery']):
                assigned = 'On File'
            else:
                assigned = 'Hemraj'
        else:
            # assign round-robin for non-misc categories
            assigned = staff[i % len(staff)]
            i += 1
        try:
            cur.execute('UPDATE emails SET assigned_to=? WHERE id=?', (assigned, eid))
            updates += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    return updates
