Webmail Scraper & Dashboard

Overview
- A small Flask app that scrapes https://webmail.incometax.gov.in, stores mails from past 60 days, categorizes them, assigns them to staff based on the work order Word file stored in Desktop/webmail scrapper, and exposes a web dashboard to view and edit statuses.

Important: this is provided as-is. Playwright login selectors may need adjustment depending on the actual webmail UI.

Setup (macOS)
1. Install Python 3.10+ and create a virtualenv:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Install Playwright browsers:

```bash
python -m playwright install
```

3. Set environment variables (you can export these in your shell or create a small launch script):

```bash
export WEBMAIL_USER=jaipur.dcit.int
export WEBMAIL_PWD='Arvind#2026'
export WEBMAIL_ADMIN_PWD='change_this_admin_pwd'
```

4. Run the app:

```bash
python app.py
```

The server listens on http://0.0.0.0:8000. Open that URL in a browser to view the dashboard.

Scheduling
- The app starts a background scheduler (APScheduler) and will run the scrape job daily at 10:30 AM local time when the Flask app is running. For a persistent always-on service, create a launchd job (macOS) or run it on a server.

Start/Stop server (simple):
- Start: `python app.py`
- Stop: Press Ctrl+C in the terminal where `app.py` is running.

Notes
- If login fails, open `scraper.py` and adjust the `selectors` and `row_selectors` lists to match the webmail DOM. I attempted common selectors but sites differ.
- The script looks for a .docx file in `~/Desktop/webmail scrapper` to extract staff names. Ensure the work order Word file is present there.
