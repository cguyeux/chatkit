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

# Precompute at BUILD time what 140 mvCPU cannot do at request time: the OCR'd
# doctrine index (doctrine_chunks.json) and the page images (pages/*.png) --
# see app/local_search.py, app/content.py and app/build_doctrine_index.py.
# doctrine_pages.json (vision transcription, trainer-reviewed) is committed
# with the sources, never regenerated here.
RUN cd /app/app && python build_doctrine_index.py

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    OPENAI_AGENTS_DISABLE_TRACING=1

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
