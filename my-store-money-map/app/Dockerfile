FROM python:3.13-alpine
WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
ENV PORT=8080 DATA_DIR=/data
EXPOSE 8080
VOLUME ["/data"]
CMD ["python", "/app/server.py"]
