FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "fastapi==0.115.0" \
    "uvicorn==0.32.0" \
    "httpx==0.27.2"

WORKDIR /app

COPY main.py /app/main.py

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
