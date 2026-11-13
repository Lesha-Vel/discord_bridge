FROM docker.io/library/python:3.13-alpine
RUN apk upgrade && adduser -Du 9692 py
USER py
RUN pip install --no-cache-dir discord.py
COPY server.py /
ENTRYPOINT [ "python", "/server.py" ]
