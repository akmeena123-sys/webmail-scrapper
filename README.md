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

### Docker (recommended for hosting)

Build and run locally with Docker:

```bash
docker build -t webmail-scrapper:latest .
docker run -p 8080:8080 --env-file .env webmail-scrapper:latest
# open http://127.0.0.1:8080
```

### Auto-build via GitHub Actions + GHCR

This repository includes a workflow that builds a container image and pushes it to GitHub Container Registry (`ghcr.io/<owner>/webmail-scrapper`) on each push to `main`.

You can deploy the pushed image to a host (Render, Railway, DigitalOcean, etc.) or connect this repository directly in Render and enable auto-deploys for a managed URL.

Recommended quick host: Render.com — connect the GitHub repository and create a new Web Service, or create a new service from a Docker image and point to `ghcr.io/<owner>/webmail-scrapper:latest`.

2. Install Playwright browsers:

```bash
python -m playwright install
```

3. Set environment variables (you can export these in your shell or create a small launch script). Do NOT store real passwords in the repository.

Create a local `.env` file (see `.env.example`) with values for `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, and `WEBMAIL_ADMIN_PWD`.

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
