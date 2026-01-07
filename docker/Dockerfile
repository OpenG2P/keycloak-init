FROM python:3.9-slim

WORKDIR /app

RUN pip install requests pyyaml

COPY create_clients.py .

CMD ["python", "create_clients.py"]
