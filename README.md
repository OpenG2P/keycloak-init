# Keycloak Client Init

This project provides a Docker-based utility and a Helm chart to automate the creation of Keycloak clients with specific configurations as per OpenG2P requirements.

## Overview

The solution consists of:
1.  **Docker Image**: Contains a Python script that interacts with the Keycloak Admin REST API to create and configure clients.
2.  **Helm Chart**: Deploys a Kubernetes Job that runs the Docker image. It allows defining clients in `values.yaml` which are mounted as a ConfigMap.

## Prerequisites

- Keycloak 24.x
- Kubernetes Cluster
- Helm 3.x (Required for lookup function support)

## Usage

### 1. Build Docker Image

Build the Docker image and push.
_IMPORTANT: Build Docker on Ubuntu machine and not MacOS as you may face architecture mismatch issues._

```bash
cd docker
docker build -t openg2p/keycloak-init:develop .
docker push openg2p/keycloak-init:develop 
```

### 2. Configure and Run Helm Chart

Update `helm/values.yaml` with your client details. Few default clients have beeen added.

```yaml
image:
  repository: your-registry/keycloak-init
  tag: "1.0.0"

keycloak:
  url: "http://keycloak.default.svc.cluster.local:8080"
  user: "admin"
  password: "admin-password"
  realm: "master"

clients:
  - clientId: "openg2p-sr-odk-prod"
    name: "Social Registry ODK Prod"
    redirectUris: 
      - "*"
    # secret: "optional-secret" # If omitted, a random secret is generated and stored in a K8s Secret
  - clientId: "another-client"
```

## Features

-   **Idempotent Execution**: The script checks if a client exists. If it does, it updates it; otherwise, it creates it.
-   **Client Configuration**:

## Notes
- A user in Keycloak has been created only to manage clients with following Keycloak roles:
  - manage-clients
  - view-clients
  - query-clients
  - default-role-master
