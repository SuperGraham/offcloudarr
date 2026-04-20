import os
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

BLACKHOLE_DIRS = os.environ.get('BLACKHOLE_DIRS', '/blackhole').split(',')
OFFCLOUD_API_KEY = os.environ.get('OFFCLOUD_API_KEY')
OFFCLOUD_STORAGE = os.environ.get('OFFCLOUD_STORAGE', 'cloud').lower()
OFFCLOUD_API_URL = f'https://offcloud.com/api/{OFFCLOUD_STORAGE}'
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))


def send_to_offcloud(magnet):
    response = requests.post(
        OFFCLOUD_API_URL,
        headers={
            'Authorization': f'Bearer {OFFCLOUD_API_KEY}',
            'Content-Type': 'application/json'
        },
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

    logging.info(f'Sending to Offcloud: {filepath}')
    result = send_to_offcloud(magnet)
    logging.info(f'Offcloud response: {result}')

    # Move to processed folder within the same blackhole directory
    processed_dir = os.path.join(os.path.dirname(filepath), 'processed')
    os.makedirs(processed_dir, exist_ok=True)
    processed_path = os.path.join(processed_dir, os.path.basename(filepath))
    os.rename(filepath, processed_path)
    logging.info(f'Moved to processed: {processed_path}')


def watch():
    for blackhole_dir in BLACKHOLE_DIRS:
        os.makedirs(blackhole_dir, exist_ok=True)
        logging.info(f'Watching {blackhole_dir} for magnet files...')

    while True:
        for blackhole_dir in BLACKHOLE_DIRS:
            try:
                for filename in os.listdir(blackhole_dir):
                    if filename.endswith('.magnet'):
                        filepath = os.path.join(blackhole_dir, filename)
                        try:
                            process_magnet_file(filepath)
                        except Exception as e:
                            logging.error(f'Error processing {filepath}: {e}')
            except Exception as e:
                logging.error(f'Error watching {blackhole_dir}: {e}')
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    if not OFFCLOUD_API_KEY:
        raise RuntimeError('OFFCLOUD_API_KEY environment variable is not set')
    watch()
