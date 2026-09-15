# [ChatKit] FastAPI backend — self-contained image for Scaleway Serverless Containers.
# Reads OPENAI_API_KEY from the environment (injected as a Scaleway secret).
# Listens on $PORT (Scaleway injects 8080); CORS is already open in app.main.
FROM python:3.11-slim

WORKDIR /app

# System certs for outbound HTTPS to the OpenAI/Mistral APIs, plus Tesseract
# OCR (French language pack): the bundled doctrine PDF has no extractable
# text layer on its content pages (design/layout export), only OCR recovers
# it -- see app/local_search.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tesseract-ocr \
    tesseract-ocr-fra \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# App package (includes bundled data: kc_graph1.json, the doctrine PDF served at /static, widgets).
COPY app /app/app

# Precompute the OCR'd doctrine index at BUILD time (baked into the image as
# doctrine_chunks.json), not lazily on a user's first request: 140 mvCPU on
# Scaleway is far too little to OCR 24 pages within a request's lifetime --
# see app/local_search.py and app/build_doctrine_index.py.
RUN cd /app/app && python build_doctrine_index.py

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
