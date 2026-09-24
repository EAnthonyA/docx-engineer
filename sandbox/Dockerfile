FROM python:3.12-slim

RUN pip install --no-cache-dir "python-docx==1.1.2" \
    && adduser --disabled-password --no-create-home appuser

WORKDIR /work

COPY entrypoint.py /work/entrypoint.py
COPY docxkit.py /work/docxkit.py
COPY document_io.py /work/document_io.py

USER appuser

CMD ["python", "/work/entrypoint.py"]
