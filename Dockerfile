FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
CMD exec python -m uvicorn src.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}
