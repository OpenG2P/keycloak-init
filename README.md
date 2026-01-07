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

## Directory Structure

```
keycloak-init/
├── docker/
│   ├── Dockerfile
│   └── create_clients.py
└── helm/
    ├── Chart.yaml
    ├── values.yaml
    └── templates/
```

## Usage

### 1. Build Docker Image

Build the Docker image and push it to your registry.

```bash
cd docker
docker build -t your-registry/keycloak-init:1.0.0 .
docker push your-registry/keycloak-init:1.0.0
```

### 2. Configure Helm Chart

Update `helm/values.yaml` with your Keycloak details and the list of clients you want to create.

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

### 3. Install Helm Chart

```bash
helm install keycloak-init ./helm
```

This will spawn a Job that runs the python script to create/update the clients in Keycloak.

## Secret Management

-   **Automatic Generation**: If a client secret is not provided in `values.yaml`, the Helm chart automatically generates a random 32-character alphanumeric secret.
-   **Persistence**: The secret is stored in a Kubernetes Secret named after the `clientId`.
-   **Idempotency**: On subsequent upgrades, the chart checks for an existing Kubernetes Secret using the `lookup` function. If it exists, the existing secret is preserved; otherwise, a new one is generated.
-   **Injection**: The secret is mounted into the job container at `/secrets/<clientId>/client_secret` and consumed by the script.

## Features

-   **Idempotent Execution**: The script checks if a client exists. If it does, it updates it; otherwise, it creates it.
-   **Client Configuration**:
    -   Standard Flow and Service Accounts enabled.
    -   Direct Access Grants disabled.
    -   Front Channel Logout enabled.
-   **Mappers Configuration**:
    -   Removes `Audience Resolve` mapper.
    -   Adds `Audience` mapper with `included.client.audience` set to the client ID.
    -   Adds `Client Roles` mapper (with access token and introspection claims).
    -   Adds standard mappers: `email`, `address`, `email verified`, `Client Host`, `full name`, `Client IP Address`, `allowed web origins`, `birthdate`, `gender`, `Client ID`, `acr loa level`, `family name`.
-   **Scope Configuration**:
    -   Retains `roles` scope (previously removed, now preserved).

## Configuration Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `keycloak.url` | Keycloak base URL | `http://keycloak...` |
| `keycloak.user` | Admin username | `admin` |
| `keycloak.password` | Admin password | `admin` |
| `keycloak.existingSecret` | Secret name containing password | `""` |
| `clients` | List of clients to create | `[]` |

