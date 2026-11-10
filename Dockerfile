FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home iron \
    && mkdir -p /data /reports && chown iron:iron /data /reports
WORKDIR /app
COPY requirements-cloud.txt /app/
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY app.py cloud.py morning_report.py muscles.py coach.py decision.py chat.py providers.py push.py /app/
COPY static /app/static
USER iron
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IRON_DATA_DIR=/data IRON_REPORT_DIR=/reports
EXPOSE 8765
CMD ["python3", "app.py"]
