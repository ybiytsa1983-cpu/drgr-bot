FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir flask==3.0.0
EXPOSE 5001
CMD ["python", "server.py"]
