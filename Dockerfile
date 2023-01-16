FROM python:3.11

COPY . /app
EXPOSE 9000
WORKDIR app

RUN pip install -r requirements.txt

CMD ["python3", "main.py"]
