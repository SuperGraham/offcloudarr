FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl --no-install-recommends && rm -rf /var/lib/apt/lists/*

RUN pip install requests bencodepy --no-cache-dir

COPY VERSION .
COPY offcloudarr.py .

RUN VERSION=$(cat VERSION) && echo "VERSION=$VERSION" > /etc/offcloudarr_version

EXPOSE 6771

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:6771/health || exit 1

CMD ["python", "offcloudarr.py"]
