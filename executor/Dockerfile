FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "fastapi==0.115.0" \
    "uvicorn[standard]==0.32.0" \
    "docker==7.1.0" \
    "pydantic==2.9.2"

WORKDIR /app

COPY main.py /app/main.py

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
