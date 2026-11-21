FROM docker.io/library/python:3.13-alpine
WORKDIR /app
COPY server.py requirements.txt .
RUN apk upgrade && adduser -Du 9692 py
USER py
RUN pip install -r /app/requirements.txt
ENTRYPOINT [ "python", "/app/server.py" ]
