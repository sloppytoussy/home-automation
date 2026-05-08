FROM python:3.9-slim
WORKDIR /app
COPY projects/home-hub/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY projects/home-hub /app/projects/home-hub
WORKDIR /app/projects/home-hub
ENV PYTHONPATH=/app
EXPOSE 5006
CMD ["python", "-m", "flask", "--app", "dashboard.app", "run", "--host", "0.0.0.0", "--port", "5006"]
