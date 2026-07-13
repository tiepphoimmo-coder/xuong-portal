# Xuong KOL - Van phong (portal) cho VPS Arcane
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# code studio (app.py, store.py, auth.py, create_user.py, web/)
COPY studio/ /app/studio/

ENV STUDIO_MODE=portal \
    STUDIO_ORIGIN=vps \
    DATA_HOME=/data \
    PORT=8091 \
    HOST=0.0.0.0

VOLUME /data
EXPOSE 8091

WORKDIR /app/studio
CMD ["python", "app.py"]
