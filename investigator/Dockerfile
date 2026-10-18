FROM python:3.12-slim
# git is needed to read commit diffs from the mounted repository
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global --add safe.directory /repo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY investigator ./investigator
ENTRYPOINT ["python", "-m", "investigator.cli"]
