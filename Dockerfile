FROM docker-hub.docker.lamoda.ru/python:3.14.0a2-alpine
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY k8s-deployments-cleaner.py .
ENTRYPOINT ["python", "k8s-deployments-cleaner.py"]