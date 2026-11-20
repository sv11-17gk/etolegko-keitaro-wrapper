FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД обёртки в volume (перезаписывается docker-compose.yml при необходимости)
ENV DATABASE_URL=sqlite:////data/wrapper.db
RUN mkdir -p /data

EXPOSE 8000

# миграции накатываются при старте приложения (см. app/main.py)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
