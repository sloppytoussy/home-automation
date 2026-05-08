FROM python:3.9-slim
WORKDIR /app

COPY projects/water-monitor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY projects/water-monitor /app/projects/water-monitor
WORKDIR /app/projects/water-monitor
ENV PYTHONPATH=/app

EXPOSE 5002

# Default: collector. Override CMD for the dashboard service.
CMD ["python", "-m", "collector.main"]
