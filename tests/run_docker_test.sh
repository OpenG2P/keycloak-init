#!/bin/bash
set -e

# Get absolute path to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# 1. Build the docker image
echo "Building Docker image .."
docker build -t keycloak-init:develop "$REPO_ROOT/docker"

# 2. Setup Test Data
CLIENT_ID="test-client-local"
SECRET_VAL="mounted-secret-ABC-123"
SECRETS_DIR="$SCRIPT_DIR/secrets"

# Create secrets directory structure (simulating K8s volume mount)
# Path: /secrets/<clientId>/client_secret
mkdir -p "$SECRETS_DIR/$CLIENT_ID"
echo -n "$SECRET_VAL" > "$SECRETS_DIR/$CLIENT_ID/client_secret"
echo "Created dummy secret at $SECRETS_DIR/$CLIENT_ID/client_secret"

# 3. Run the container
# We mount local_clients.yaml to /config/clients.yaml
# We mount the secrets directory to /secrets
echo "Running the docker .."
docker run --rm \
    --name keycloak-init-test \
    --env-file "$SCRIPT_DIR/local.env" \
    -v "$SCRIPT_DIR/local_clients.yaml":/config/clients.yaml \
    -v "$SECRETS_DIR":/secrets \
    keycloak-init:develop

echo "Test complete."
