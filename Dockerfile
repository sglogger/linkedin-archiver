FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY pyproject.toml ./
COPY linkedin_archiver ./linkedin_archiver
RUN pip install --no-deps . \
    && mkdir -p /data/media /data/export \
    && chown -R pwuser:pwuser /data
USER pwuser
ENTRYPOINT ["python", "-m", "linkedin_archiver"]
CMD ["run"]
