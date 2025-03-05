FROM harbor.lamodatech.ru/dockerhub/python:3.12-alpine
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY k8s-deployments-cleaner.py .
ENTRYPOINT ["python", "k8s-deployments-cleaner.py"]