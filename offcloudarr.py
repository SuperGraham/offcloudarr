import os
import time
import hashlib
import requests
import logging
import bencodepy
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

BLACKHOLE_DIRS = [d for d in os.environ.get('BLACKHOLE_DIRS', '').split(',') if d.strip()]
OFFCLOUD_API_KEY = os.environ.get('OFFCLOUD_API_KEY')
OFFCLOUD_STORAGE = os.environ.get('OFFCLOUD_STORAGE', 'cloud').lower()
OFFCLOUD_API_URL = f'https://offcloud.com/api/{OFFCLOUD_STORAGE}'
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))
WEB_PORT = 6771

# Read version from file baked into image
try:
    with open('/app/VERSION') as f:
        VERSION = f.read().strip()
except Exception:
    VERSION = 'unknown'

HEADERS = {
    'Authorization': f'Bearer {OFFCLOUD_API_KEY}',
    'Content-Type': 'application/json'
}

# In-memory state
activity_log = deque(maxlen=50)
start_time = datetime.now(timezone.utc)
blackhole_enabled = False
seen_request_ids = set()


def log_activity(event_type, filename, message, offcloud_response=None):
    entry = {
        'time': datetime.now(timezone.utc).isoformat(),
        'type': event_type,
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
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%237c6af7'/><path d='M8 20a4 4 0 01-.5-7.97 6 6 0 0111.44-1.5A4 4 0 0122 20H8z' fill='white'/><path d='M16 14v7M13 18l3 3 3-3' stroke='%237c6af7' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/></svg>">
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
  .version {
    font-size: 0.7rem;
    color: var(--muted);
    font-family: var(--mono);
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
  .badge.off {
    background: var(--muted);
    color: var(--bg);
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
  <span class="version">v__VERSION__</span>
  <span class="badge __BLACKHOLE_BADGE__">Blackhole __BLACKHOLE_STATUS__</span>
</header>

<div class="grid">
  <div class="card">
    <div class="card-label">Sent This Session</div>
    <div class="card-value green">__SENT__</div>
  </div>
  <div class="card">
    <div class="card-label">Duplicates</div>
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
    delta = datetime.now(timezone.utc) - start_time
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
        rows.append(f'''<div class="activity-item {entry["type"]}">
          <span class="activity-time">{t}</span>
          <div><div class="activity-name">{name}</div>{msg}</div>
          {pill}
        </div>''')

    if not rows:
        rows = ['<div class="empty">No activity yet</div>']

    html = HTML_TEMPLATE
    html = html.replace('__VERSION__', VERSION)
    html = html.replace('__SENT__', str(sent_count))
    html = html.replace('__DUPLICATES__', str(duplicate_count))
    html = html.replace('__ERRORS__', str(error_count))
    html = html.replace('__UPTIME__', format_uptime())
    html = html.replace('__STORAGE__', OFFCLOUD_STORAGE)
    html = html.replace('__POLL_INTERVAL__', str(POLL_INTERVAL))
    html = html.replace('__WEB_PORT__', str(WEB_PORT))
    html = html.replace('__BLACKHOLE_DIRS__', '<br>'.join(BLACKHOLE_DIRS) if BLACKHOLE_DIRS else 'Not configured')
    html = html.replace('__ACTIVITY__', '\n'.join(rows))
    html = html.replace('__BLACKHOLE_STATUS__', 'Active' if blackhole_enabled else 'Inactive')
    html = html.replace('__BLACKHOLE_BADGE__', '' if blackhole_enabled else 'off')
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
        move_to_processed(filepath)
        return

    logging.info(f'Sending to Offcloud: {filename}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')

    request_id = result.get('requestId')
    if request_id and request_id in seen_request_ids:
        logging.warning(f'Duplicate detected — already in Offcloud: {result.get("fileName", "")}')
        log_activity('duplicate', filename, f'Already in Offcloud: {result.get("fileName", "")}', result)
    else:
        if request_id:
            seen_request_ids.add(request_id)
        log_activity('sent', filename, f'Offcloud: {result.get("fileName", "")}', result)

    move_to_processed(filepath)


def process_torrent_file(filepath):
    filename = os.path.basename(filepath)
    logging.info(f'Converting torrent to magnet: {filename}')
    magnet = torrent_to_magnet(filepath)
    logging.info(f'Sending to Offcloud: {filename}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')

    request_id = result.get('requestId')
    if request_id and request_id in seen_request_ids:
        logging.warning(f'Duplicate detected — already in Offcloud: {result.get("fileName", "")}')
        log_activity('duplicate', filename, f'Already in Offcloud: {result.get("fileName", "")}', result)
    else:
        if request_id:
            seen_request_ids.add(request_id)
        log_activity('sent', filename, f'Offcloud: {result.get("fileName", "")}', result)

    move_to_processed(filepath)


def move_to_processed(filepath):
    processed_dir = os.path.join(os.path.dirname(filepath), 'processed')
    os.makedirs(processed_dir, exist_ok=True)
    processed_path = os.path.join(processed_dir, os.path.basename(filepath))
    os.rename(filepath, processed_path)
    logging.info(f'Moved to processed: {processed_path}')


def check_blackhole_dirs():
    accessible = []
    for d in BLACKHOLE_DIRS:
        if os.path.isdir(d):
            accessible.append(d)
            logging.info(f'Blackhole folder found: {d}')
        else:
            logging.warning(f'Blackhole folder not found, skipping: {d}')
    return accessible


def watch(dirs):
    logging.info('Blackhole polling active')
    while True:
        for blackhole_dir in dirs:
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

    banner = r"""
  ___  __  __      _                _
 / _ \/ _|/ _|    | |              | |
| | | | |_| |_ ___| | ___  _   _  | | __ _ _ __ _ __
| | | |  _|  _/ __| |/ _ \| | | | | |/ _` | '__| '__|
| |_| | | | || (__| | (_) | |_| | | | (_| | |  | |
 \___/|_| |_| \___|_|\___/ \__,_| |_|\__,_|_|  |_|
"""
    print(banner)
    logging.info(f'Offcloudarr v{VERSION} starting')

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    accessible_dirs = check_blackhole_dirs()
    if accessible_dirs:
        blackhole_enabled = True
        watch_thread = threading.Thread(target=watch, args=(accessible_dirs,), daemon=True)
        watch_thread.start()
    else:
        logging.info('No blackhole folders configured or accessible — polling disabled')

    while True:
        time.sleep(60)
