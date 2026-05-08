FROM python:3.9-slim
WORKDIR /app

COPY projects/power-dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY projects/power-dashboard /app/projects/power-dashboard
WORKDIR /app/projects/power-dashboard
ENV PYTHONPATH=/app

EXPOSE 5001

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5001", "dashboard.app:app"]
