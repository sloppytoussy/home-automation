FROM python:3.9-slim
WORKDIR /app

COPY projects/dns-monitor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY projects/dns-monitor /app/projects/dns-monitor
WORKDIR /app/projects/dns-monitor
ENV PYTHONPATH=/app

EXPOSE 5000

# Default: collector. Override CMD in compose for the dashboard service.
CMD ["python", "-m", "collector.main"]
