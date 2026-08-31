# [ChatKit] FastAPI backend — self-contained image for Scaleway Serverless Containers.
# Reads OPENAI_API_KEY from the environment (injected as a Scaleway secret).
# Listens on $PORT (Scaleway injects 8080); CORS is already open in app.main.
FROM python:3.11-slim

WORKDIR /app

# System certs for outbound HTTPS to the OpenAI API.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# App package (includes bundled data: kc_graph1.json, the doctrine PDF served at /static, widgets).
COPY app /app/app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
