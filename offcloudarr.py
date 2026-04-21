import os
import time
import hashlib
import requests
import logging
import bencodepy
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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
HEALTH_PORT = int(os.environ.get('HEALTH_PORT', '8080'))

HEADERS = {
    'Authorization': f'Bearer {OFFCLOUD_API_KEY}',
    'Content-Type': 'application/json'
}

# In-memory cache of hashes sent in this session
sent_hashes = set()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logs


def start_health_server():
    server = HTTPServer(('0.0.0.0', HEALTH_PORT), HealthHandler)
    logging.info(f'Health check endpoint started on port {HEALTH_PORT}')
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

    # Check in-memory session cache first
    if hash_to_check in sent_hashes:
        logging.warning(f'Duplicate detected — already sent in this session: {hash_to_check}')
        return True

    # Check Offcloud history
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
    with open(filepath, 'r') as f:
        magnet = f.read().strip()

    if not magnet.startswith('magnet:'):
        logging.warning(f'Skipping {filepath} - does not contain a magnet link')
        return

    if is_duplicate(magnet):
        logging.warning(f'Skipping duplicate: {filepath}')
        move_to_processed(filepath)
        return

    logging.info(f'Sending to Offcloud: {filepath}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')

    info_hash = extract_info_hash_from_magnet(magnet)
    if info_hash:
        sent_hashes.add(info_hash)

    move_to_processed(filepath)


def process_torrent_file(filepath):
    logging.info(f'Converting torrent to magnet: {filepath}')
    magnet = torrent_to_magnet(filepath)
    logging.info(f'Magnet: {magnet}')

    if is_duplicate(magnet):
        logging.warning(f'Skipping duplicate: {filepath}')
        move_to_processed(filepath)
        return

    logging.info(f'Sending to Offcloud: {filepath}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')

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
            except Exception as e:
                logging.error(f'Error watching {blackhole_dir}: {e}')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    if not OFFCLOUD_API_KEY:
        raise RuntimeError('OFFCLOUD_API_KEY environment variable is not set')

    # Start health check server in background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    watch()
