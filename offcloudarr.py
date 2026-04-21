import os
import time
import hashlib
import requests
import logging
import bencodepy
import threading
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

BLACKHOLE_DIRS = os.environ.get('BLACKHOLE_DIRS', '/blackhole').split(',')
OFFCLOUD_API_KEY = os.environ.get('OFFCLOUD_API_KEY')
OFFCLOUD_STORAGE = os.environ.get('OFFCLOUD_STORAGE', 'cloud').lower()
OFFCLOUD_API_URL = f'https://offcloud.com/api/{OFFCLOUD_STORAGE}'
OFFCLOUD_HISTORY_URL = 'https://offcloud.com/api/cloud/history'
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))
WEB_PORT = 6771

HEADERS = {
    'Authorization': f'Bearer {OFFCLOUD_API_KEY}',
    'Content-Type': 'application/json'
}

# In-memory state
sent_hashes = set()
activity_log = deque(maxlen=50)
start_time = datetime.utcnow()


def log_activity(event_type, filename, message, offcloud_response=None):
    entry = {
        'time': datetime.utcnow().isoformat(),
        'type': event_type,  # 'sent', 'duplicate', 'error', 'skipped'
        'filename': filename,
        'message': message,
        'response': offcloud_response
    }
    activity_log.appendleft(entry)


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Offcloudarr</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --border: #1e1e2e;
    --accent: #7c6af7;
    --accent2: #f7916a;
    --green: #4af7a0;
    --red: #f74a6a;
    --yellow: #f7e04a;
    --text: #e0e0f0;
    --muted: #5a5a7a;
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Syne', sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    min-height: 100vh;
    padding: 2rem;
  }
  header {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 2.5rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 1.5rem;
  }
  header h1 {
    font-family: var(--sans);
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .badge {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.2rem 0.6rem;
    border-radius: 2px;
    background: var(--green);
    color: #000;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1.25rem;
  }
  .card-label {
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 0.5rem;
  }
  .card-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--accent);
  }
  .card-value.green { color: var(--green); }
  .card-value.red { color: var(--red); }
  .card-value.yellow { color: var(--yellow); }
  .section-title {
    font-family: var(--sans);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 1rem;
    margin-top: 2rem;
  }
  .config-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 0.5rem;
    margin-bottom: 2rem;
  }
  .config-item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.75rem 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
  }
  .config-key { color: var(--muted); font-size: 0.8rem; }
  .config-val { color: var(--text); font-size: 0.8rem; word-break: break-all; text-align: right; }
  .activity-list { display: flex; flex-direction: column; gap: 0.4rem; }
  .activity-item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--muted);
    border-radius: 4px;
    padding: 0.75rem 1rem;
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 1rem;
    align-items: start;
    font-size: 0.8rem;
  }
  .activity-item.sent { border-left-color: var(--green); }
  .activity-item.duplicate { border-left-color: var(--yellow); }
  .activity-item.error { border-left-color: var(--red); }
  .activity-item.skipped { border-left-color: var(--muted); }
  .activity-time { color: var(--muted); white-space: nowrap; font-size: 0.7rem; }
  .activity-name { color: var(--text); word-break: break-word; }
  .activity-msg { color: var(--muted); font-size: 0.7rem; margin-top: 0.2rem; }
  .pill {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 0.15rem 0.5rem;
    border-radius: 2px;
    white-space: nowrap;
  }
  .pill.sent { background: rgba(74,247,160,0.15); color: var(--green); }
  .pill.duplicate { background: rgba(247,224,74,0.15); color: var(--yellow); }
  .pill.error { background: rgba(247,74,106,0.15); color: var(--red); }
  .pill.skipped { background: rgba(90,90,122,0.15); color: var(--muted); }
  .empty { color: var(--muted); font-size: 0.8rem; padding: 2rem; text-align: center; }
  .auto-refresh { color: var(--muted); font-size: 0.7rem; margin-top: 2rem; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Offcloudarr</h1>
  <span class="badge">Running</span>
</header>

<div class="grid">
  <div class="card">
    <div class="card-label">Sent This Session</div>
    <div class="card-value green">__SENT__</div>
  </div>
  <div class="card">
    <div class="card-label">Duplicates Skipped</div>
    <div class="card-value yellow">__DUPLICATES__</div>
  </div>
  <div class="card">
    <div class="card-label">Errors</div>
    <div class="card-value red">__ERRORS__</div>
  </div>
  <div class="card">
    <div class="card-label">Uptime</div>
    <div class="card-value">__UPTIME__</div>
  </div>
</div>

<div class="section-title">Configuration</div>
<div class="config-grid">
  <div class="config-item"><span class="config-key">Storage</span><span class="config-val">__STORAGE__</span></div>
  <div class="config-item"><span class="config-key">Poll Interval</span><span class="config-val">__POLL_INTERVAL__s</span></div>
  <div class="config-item"><span class="config-key">Web Port</span><span class="config-val">__WEB_PORT__</span></div>
  <div class="config-item"><span class="config-key">Blackhole Dirs</span><span class="config-val">__BLACKHOLE_DIRS__</span></div>
</div>

<div class="section-title">Recent Activity</div>
<div class="activity-list">
__ACTIVITY__
</div>
<div class="auto-refresh">Auto-refreshes every 10 seconds</div>
<script>setTimeout(() => location.reload(), 10000);</script>
</body>
</html>'''


def format_uptime():
    delta = datetime.utcnow() - start_time
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f'{hours}h {minutes}m'
    elif minutes > 0:
        return f'{minutes}m {seconds}s'
    return f'{seconds}s'


def render_html():
    sent_count = sum(1 for e in activity_log if e['type'] == 'sent')
    duplicate_count = sum(1 for e in activity_log if e['type'] == 'duplicate')
    error_count = sum(1 for e in activity_log if e['type'] == 'error')

    rows = []
    for entry in activity_log:
        t = entry['time'][11:19]
        pill = f'<span class="pill {entry["type"]}">{entry["type"]}</span>'
        name = entry['filename']
        msg = f'<div class="activity-msg">{entry["message"]}</div>' if entry['message'] else ''
        rows.append(f'''<div class="activity-item {entry['type']}">
          <span class="activity-time">{t}</span>
          <div><div class="activity-name">{name}</div>{msg}</div>
          {pill}
        </div>''')

    if not rows:
        rows = ['<div class="empty">No activity yet</div>']

    html = HTML_TEMPLATE
    html = html.replace('__SENT__', str(sent_count))
    html = html.replace('__DUPLICATES__', str(duplicate_count))
    html = html.replace('__ERRORS__', str(error_count))
    html = html.replace('__UPTIME__', format_uptime())
    html = html.replace('__STORAGE__', OFFCLOUD_STORAGE)
    html = html.replace('__POLL_INTERVAL__', str(POLL_INTERVAL))
    html = html.replace('__WEB_PORT__', str(WEB_PORT))
    html = html.replace('__BLACKHOLE_DIRS__', '<br>'.join(BLACKHOLE_DIRS))
    html = html.replace('__ACTIVITY__', '\n'.join(rows))
    return html


class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path == '/' or self.path == '/ui':
            html = render_html().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_web_server():
    server = HTTPServer(('0.0.0.0', WEB_PORT), WebHandler)
    logging.info(f'Web UI and health check available on port {WEB_PORT}')
    server.serve_forever()


def get_offcloud_history():
    response = requests.get(OFFCLOUD_HISTORY_URL, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def extract_info_hash_from_magnet(magnet):
    for part in magnet.split('&'):
        if part.startswith('magnet:?xt=urn:btih:') or part.startswith('xt=urn:btih:'):
            return part.split(':')[-1].lower()
    return None


def is_duplicate(magnet):
    hash_to_check = extract_info_hash_from_magnet(magnet)
    if not hash_to_check:
        return False

    if hash_to_check in sent_hashes:
        logging.warning(f'Duplicate detected — already sent in this session: {hash_to_check}')
        return True

    try:
        history = get_offcloud_history()
        for item in history:
            existing_link = item.get('originalLink', '')
            existing_hash = extract_info_hash_from_magnet(existing_link)
            if existing_hash and existing_hash.lower() == hash_to_check.lower():
                logging.warning(f'Duplicate detected — already in Offcloud: {item.get("fileName", "")}')
                return True
    except Exception as e:
        logging.error(f'Error checking Offcloud history: {e}')

    return False


def torrent_to_magnet(filepath):
    with open(filepath, 'rb') as f:
        torrent_data = bencodepy.decode(f.read())
    info = torrent_data[b'info']
    info_hash = hashlib.sha1(bencodepy.encode(info)).hexdigest()
    name = info.get(b'name', b'').decode('utf-8', errors='ignore')
    magnet = f'magnet:?xt=urn:btih:{info_hash}'
    if name:
        magnet += f'&dn={requests.utils.quote(name)}'
    return magnet


def send_to_offcloud(magnet):
    response = requests.post(
        OFFCLOUD_API_URL,
        headers=HEADERS,
        json={'url': magnet}
    )
    response.raise_for_status()
    return response.json()


def process_magnet_file(filepath):
    filename = os.path.basename(filepath)
    with open(filepath, 'r') as f:
        magnet = f.read().strip()

    if not magnet.startswith('magnet:'):
        logging.warning(f'Skipping {filepath} - does not contain a magnet link')
        log_activity('skipped', filename, 'Not a valid magnet link')
        return

    if is_duplicate(magnet):
        logging.warning(f'Skipping duplicate: {filepath}')
        log_activity('duplicate', filename, 'Already exists in Offcloud or sent this session')
        move_to_processed(filepath)
        return

    logging.info(f'Sending to Offcloud: {filepath}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')
    log_activity('sent', filename, f'Offcloud: {result.get("fileName", "")}', result)

    info_hash = extract_info_hash_from_magnet(magnet)
    if info_hash:
        sent_hashes.add(info_hash)

    move_to_processed(filepath)


def process_torrent_file(filepath):
    filename = os.path.basename(filepath)
    logging.info(f'Converting torrent to magnet: {filepath}')
    magnet = torrent_to_magnet(filepath)
    logging.info(f'Magnet: {magnet}')

    if is_duplicate(magnet):
        logging.warning(f'Skipping duplicate: {filepath}')
        log_activity('duplicate', filename, 'Already exists in Offcloud or sent this session')
        move_to_processed(filepath)
        return

    logging.info(f'Sending to Offcloud: {filepath}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')
    log_activity('sent', filename, f'Offcloud: {result.get("fileName", "")}', result)

    info_hash = extract_info_hash_from_magnet(magnet)
    if info_hash:
        sent_hashes.add(info_hash)

    move_to_processed(filepath)


def move_to_processed(filepath):
    processed_dir = os.path.join(os.path.dirname(filepath), 'processed')
    os.makedirs(processed_dir, exist_ok=True)
    processed_path = os.path.join(processed_dir, os.path.basename(filepath))
    os.rename(filepath, processed_path)
    logging.info(f'Moved to processed: {processed_path}')


def watch():
    for blackhole_dir in BLACKHOLE_DIRS:
        os.makedirs(blackhole_dir, exist_ok=True)
        logging.info(f'Watching {blackhole_dir} for magnet and torrent files...')

    while True:
        for blackhole_dir in BLACKHOLE_DIRS:
            try:
                for filename in os.listdir(blackhole_dir):
                    filepath = os.path.join(blackhole_dir, filename)
                    try:
                        if filename.endswith('.magnet'):
                            process_magnet_file(filepath)
                        elif filename.endswith('.torrent'):
                            process_torrent_file(filepath)
                    except Exception as e:
                        logging.error(f'Error processing {filepath}: {e}')
                        log_activity('error', filename, str(e))
            except Exception as e:
                logging.error(f'Error watching {blackhole_dir}: {e}')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    if not OFFCLOUD_API_KEY:
        raise RuntimeError('OFFCLOUD_API_KEY environment variable is not set')

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    watch()
