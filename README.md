# Offcloudarr

A lightweight Docker container that watches blackhole folders used by Sonarr and Radarr, picks up `.magnet` files, and automatically forwards them to [Offcloud](https://offcloud.com) for downloading.

## How It Works

1. Sonarr or Radarr grabs a release and writes a `.magnet` file to a blackhole folder
2. Offcloudarr detects the file within 10 seconds
3. The magnet link is sent to Offcloud via its API
4. The `.magnet` file is moved to a `processed/` subfolder
5. Offcloud downloads the content to your storage

## Quick Start

```yaml
services:
  offcloudarr:
    image: supergraham/offcloudarr:latest
    container_name: offcloudarr
    restart: unless-stopped
    environment:
      - TZ=UTC
      - OFFCLOUD_API_KEY=YOUR_OFFCLOUD_API_KEY
      - OFFCLOUD_STORAGE=cloud
      - POLL_INTERVAL=10
      - BLACKHOLE_DIRS=/sonarr-blackhole,/radarr-blackhole
    volumes:
      - /opt/docker/sonarr/blackhole:/sonarr-blackhole
      - /opt/docker/radarr/blackhole:/radarr-blackhole
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OFFCLOUD_API_KEY` | Yes | — | Your Offcloud API key |
| `OFFCLOUD_STORAGE` | No | `cloud` | Storage destination: `cloud` for Offcloud cloud storage |
| `BLACKHOLE_DIRS` | No | `/blackhole` | Comma-separated list of blackhole directories to watch |
| `POLL_INTERVAL` | No | `10` | How often in seconds to check blackhole folders for new magnet files |
| `TZ` | No | UTC | Timezone for log timestamps |

## Full Documentation

See the [GitHub repository](https://github.com/SuperGraham/offcloudarr) for full setup instructions.
