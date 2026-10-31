FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY linkextractor.py main.py ./

ENV WORKERS=2 THREADS=8
EXPOSE 5000

# Gunicorn gthread: WORKERS processos x THREADS threads (mesma topologia do Puma em Ruby)
CMD ["sh", "-c", "exec gunicorn -k gthread -w ${WORKERS} --threads ${THREADS} -b 0.0.0.0:5000 --timeout 30 main:app"]
