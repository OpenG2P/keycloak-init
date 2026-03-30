#!/bin/bash
set -e

# Get absolute path to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 1. Setup Test Data
CLIENT_ID="test-client-local"
SECRET_VAL="mounted-secret-ABC-123"
SECRETS_DIR="$SCRIPT_DIR/secrets"

# Create secrets directory structure (simulating K8s volume mount)
# Path: /secrets/<clientId>/client_secret
mkdir -p "$SECRETS_DIR/$CLIENT_ID"
echo -n "$SECRET_VAL" > "$SECRETS_DIR/$CLIENT_ID/client_secret"
echo "Created dummy secret at $SECRETS_DIR/$CLIENT_ID/client_secret"

# 2. Run Keycloak + init container via docker compose
echo "Starting Keycloak and running init..."
docker compose -f "$SCRIPT_DIR/docker-compose.yaml" up --build --abort-on-container-exit --exit-code-from keycloak-init

# 3. Cleanup
echo "Stopping containers..."
docker compose -f "$SCRIPT_DIR/docker-compose.yaml" down

echo "Test complete."
