FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] python-multipart websockets

COPY server.py .

EXPOSE 8100

CMD ["python", "server.py"]
