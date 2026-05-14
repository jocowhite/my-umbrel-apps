FROM python:3.13-alpine
WORKDIR /app
COPY server.py /app/server.py
ENV PORT=8080
EXPOSE 8080
USER 1000:1000
CMD ["python", "/app/server.py"]
