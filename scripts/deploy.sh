#!/usr/bin/env bash
# Deploys one service: rebuilds and restarts it, then records the deployment
# (service, git commit, message, time) so incidents can be correlated with deploys.
# Usage: ./scripts/deploy.sh <service-name>
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE=${1:?Usage: ./scripts/deploy.sh <service-name>}

# Like a real CI/CD pipeline, only deploy committed code, so every deploy maps to a git commit.
if ! git diff --quiet HEAD -- "$SERVICE"; then
  echo "Uncommitted changes in $SERVICE. Commit first."
  exit 1
fi

SHA=$(git rev-parse --short HEAD)
MSG=$(git log -1 --pretty=%s)

echo "Deploying $SERVICE at commit $SHA: $MSG"
docker compose up -d --build "$SERVICE"

docker compose exec -T postgres psql -U shop -d shop -q -v ON_ERROR_STOP=1 \
  -v service="$SERVICE" -v sha="$SHA" -v msg="$MSG" <<'SQL'
CREATE TABLE IF NOT EXISTS deployments (
    id          BIGSERIAL   PRIMARY KEY,
    service     VARCHAR(64) NOT NULL,
    git_sha     VARCHAR(40) NOT NULL,
    message     TEXT        NOT NULL,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO deployments (service, git_sha, message) VALUES (:'service', :'sha', :'msg');
SQL

ID=$(docker compose exec -T postgres psql -U shop -d shop -tA -c "SELECT max(id) FROM deployments")
echo "Recorded deployment #$ID"
