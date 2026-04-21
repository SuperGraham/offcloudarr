FROM python:3.12-slim

WORKDIR /app

RUN pip install requests torf --no-cache-dir

COPY offcloudarr.py .

CMD ["python", "offcloudarr.py"]
