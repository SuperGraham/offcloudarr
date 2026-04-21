# Offcloudarr

A lightweight Docker container that watches blackhole folders used by Sonarr and Radarr, picks up `.magnet` and `.torrent` files, and automatically forwards them to [Offcloud](https://offcloud.com) for downloading.

## How It Works

1. Sonarr or Radarr grabs a release and writes a `.magnet` or `.torrent` file to a blackhole folder
2. Offcloudarr detects the file within 10 seconds by default (configurable via `POLL_INTERVAL`)
3. The magnet link is sent to Offcloud via its API (`.torrent` files are automatically converted to magnet links)
4. The file is moved to a `processed/` subfolder
5. Offcloud downloads the content to your storage

## Prerequisites

- Docker and Docker Compose
- Sonarr and/or Radarr with Torrent Blackhole configured as the download client
- An Offcloud account with an API key (found under Account → API Key)

## Setup

### 1. Create the blackhole folders

```bash
mkdir -p /opt/docker/sonarr/blackhole
mkdir -p /opt/docker/radarr/blackhole
```

### 2. Configure Sonarr and Radarr

In both Sonarr and Radarr go to **Settings → Download Clients → Add → Torrent Blackhole** and set:

- **Torrent Folder**: `/blackhole`
- **Watch Folder**: `/downloads`
- **Save Magnet Files**: ✅ Enabled
- **Save Magnet Files Extension**: `.magnet`

Add the following volumes to your Sonarr and Radarr compose files:

**Sonarr:**
```yaml
volumes:
  - /opt/docker/sonarr/blackhole:/blackhole
  - /opt/docker/sonarr/downloads:/downloads
```

**Radarr:**
```yaml
volumes:
  - /opt/docker/radarr/blackhole:/blackhole
  - /opt/docker/radarr/downloads:/downloads
```

### 3. Deploy

Use the following compose file as a Portainer stack or with `docker compose up -d`:

```yaml
services:
  offcloudarr:
    image: supergraham/offcloudarr:latest
    container_name: offcloudarr
    environment:
      - TZ=UTC
      - OFFCLOUD_API_KEY=YOUR_OFFCLOUD_API_KEY
      - OFFCLOUD_STORAGE=cloud
      - POLL_INTERVAL=10
      - BLACKHOLE_DIRS=/sonarr-blackhole,/radarr-blackhole
    volumes:
      - /opt/docker/sonarr/blackhole:/sonarr-blackhole
      - /opt/docker/radarr/blackhole:/radarr-blackhole
    restart: unless-stopped
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OFFCLOUD_API_KEY` | Yes | — | Your Offcloud API key |
| `OFFCLOUD_STORAGE` | No | `cloud` | Storage destination: `cloud` for Offcloud cloud storage, `remote` for remote storage (e.g. Google Drive). Using `remote` is currently not supported — leave this configured as `cloud` until Offcloud adds this to their API |
| `BLACKHOLE_DIRS` | No | `/blackhole` | Comma-separated list of blackhole directories to watch. For example `BLACKHOLE_DIRS=/sonarr-blackhole,/radarr-blackhole` |
| `POLL_INTERVAL` | No | `10` | How often in seconds to check blackhole folders for new magnet files |
| `TZ` | No | UTC | Timezone for log timestamps |

## Updating

Pull the latest image and redeploy the stack:

```bash
docker pull supergraham/offcloudarr:latest
```

Then redeploy the stack.

## Logs

Check logs via Dozzle or with:

```bash
docker logs offcloudarr
```

## Processed Files

Successfully sent magnet files are moved to a `processed/` subfolder within each blackhole directory, e.g. `/opt/docker/radarr/blackhole/processed/`.