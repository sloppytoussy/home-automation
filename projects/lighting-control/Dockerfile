FROM python:3.9-slim

WORKDIR /app
COPY projects/lighting-control/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY projects/lighting-control /app/projects/lighting-control
WORKDIR /app/projects/lighting-control

EXPOSE 5005
CMD ["python", "-m", "flask", "--app", "dashboard.app", "run", "--host", "0.0.0.0", "--port", "5005"]
