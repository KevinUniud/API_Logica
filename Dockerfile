FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# SWI-Prolog e tool minimi richiesti dal bridge Python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends swi-prolog \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "server:app", "--app-dir", "server", "--host", "0.0.0.0", "--port", "5000"]
