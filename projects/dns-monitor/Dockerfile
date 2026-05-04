FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY ../../shared /app/shared

EXPOSE 5000

# Default: collector. Override CMD in compose for the dashboard service.
CMD ["python", "-m", "collector.main"]
