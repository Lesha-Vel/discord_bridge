FROM docker.io/library/python:3.13-alpine
RUN apk upgrade
RUN pip install --no-cache-dir discord.py
COPY server.py /
CMD [ "python", "/server.py" ]