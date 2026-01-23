FROM python:3.11-slim

ENV APP_HOME=/usr/src/app
WORKDIR $APP_HOME

# Installiere Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/main.py .
COPY app/static ./static

# Setze Umgebungsvariable
ENV PORT=8000
EXPOSE $PORT

# Starte die Anwendung
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]