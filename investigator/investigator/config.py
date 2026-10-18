import os

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
JAEGER_URL = os.getenv("JAEGER_URL", "http://localhost:16686")
DB_DSN = os.getenv("DB_DSN", "postgresql://shop:shop@localhost:5432/shop")
REPO_PATH = os.getenv("REPO_PATH", ".")
COMPOSE_PROJECT = os.getenv("COMPOSE_PROJECT", "incident-lab")

SERVICES = ["order-service", "inventory-service", "payment-service"]
