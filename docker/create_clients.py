import os
import sys
import yaml
import requests
import json
import time

# Configuration
KEYCLOAK_URL = os.environ.get('KEYCLOAK_URL', 'http://localhost:8080')
KEYCLOAK_USER = os.environ.get('KEYCLOAK_USER', 'admin')
KEYCLOAK_PASSWORD = os.environ.get('KEYCLOAK_PASSWORD', 'admin')
KEYCLOAK_REALM = os.environ.get('KEYCLOAK_REALM', 'master')
INPUT_FILE = os.environ.get('INPUT_FILE', '/config/clients.yaml')

def get_admin_token():
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    payload = {
        'client_id': 'admin-cli',
        'username': KEYCLOAK_USER,
        'password': KEYCLOAK_PASSWORD,
        'grant_type': 'password'
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        return response.json()['access_token']
    except Exception as e:
        print(f"Failed to get admin token: {e}")
        return None

def get_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

def create_client(base_url, realm, token, client_config):
    client_id = client_config['clientId']
    print(f"Processing client: {client_id}")

    headers = get_headers(token)
    clients_url = f"{base_url}/admin/realms/{realm}/clients"

    # Check if client exists
    response = requests.get(clients_url, headers=headers, params={'clientId': client_id})
    if response.status_code == 200:
        existing_clients = response.json()
        if existing_clients:
            print(f"Client {client_id} already exists. Skipping...")
            return
        else:
            # Create new
            print(f"Creating client {client_id}...")
            requests.post(clients_url, headers=headers, json=client_config).raise_for_status()
            # Get UUID
            response = requests.get(clients_url, headers=headers, params={'clientId': client_id})
            client_uuid = response.json()[0]['id']
    else:
        print(f"Error checking client: {response.text}")
        return

    # 2. Configure Mappers
    configure_mappers(base_url, realm, token, client_uuid, client_id)

    # 3. Retain "roles" scope (Logic to remove it is now removed)
    # configure_scopes(base_url, realm, token, client_uuid)

    print(f"Client {client_id} processed successfully.")

def configure_mappers(base_url, realm, token, client_uuid, client_id_name):
    headers = get_headers(token)
    mappers_url = f"{base_url}/admin/realms/{realm}/clients/{client_uuid}/protocol-mappers/models"
    
    # Get existing mappers
    response = requests.get(mappers_url, headers=headers)
    existing_mappers = response.json()
    
    # 1. Remove "Audience Resolve"
    for mapper in existing_mappers:
        # Specifically remove 'Audience Resolve' as per docs
        if mapper['name'] == 'Audience Resolve':
             print("Removing 'Audience Resolve' mapper...")
             requests.delete(f"{mappers_url}/{mapper['id']}", headers=headers).raise_for_status()

    # Refresh existing mappers list after deletion
    response = requests.get(mappers_url, headers=headers)
    existing_mappers = response.json()

    # 2. Add Audience Mapper
    audience_config = {
        "name": "audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": client_id_name,
            "id.token.claim": "true",
            "access.token.claim": "true"
        }
    }
    upsert_mapper(mappers_url, headers, existing_mappers, audience_config)

    # 3. Client Roles Mapper
    client_roles_config = {
        "name": "client_roles",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-client-role-mapper",
        "config": {
            "claim.name": "client_roles",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
            "introspection.token.claim": "true",
            "multivalued": "true",
            "usermodel.clientRoleMapping.clientId": client_id_name,
             "jsonType.label": "String"
        }
    }
    upsert_mapper(mappers_url, headers, existing_mappers, client_roles_config)

    # 4. Add other required mappers
    common_mappers = [
        {
            "name": "email",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "config": {
                "user.attribute": "email",
                "claim.name": "email",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "address",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-address-mapper",
            "config": {
                "user.attribute.formatted": "formatted",
                "user.attribute.country": "country",
                "user.attribute.postal_code": "postal_code",
                "user.attribute.street": "street",
                "user.attribute.region": "region",
                "user.attribute.locality": "locality",
                "claim.name": "address",
                "jsonType.label": "JSON",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "email verified",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "config": {
                "user.attribute": "emailVerified",
                "claim.name": "email_verified",
                "jsonType.label": "boolean",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "Client Host",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "config": {
                "user.session.note": "clientHost",
                "claim.name": "clientHost",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true"
            }
        },
        {
            "name": "full name",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-full-name-mapper",
            "config": {
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "Client IP Address",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "config": {
                "user.session.note": "clientAddress",
                "claim.name": "clientAddress",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true"
            }
        },
        {
            "name": "allowed web origins",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-allowed-origins-mapper",
            "config": {}
        },
        {
            "name": "birthdate",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "user.attribute": "birthdate",
                "claim.name": "birthdate",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "gender",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "user.attribute": "gender",
                "claim.name": "gender",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "Client ID",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "config": {
                "user.session.note": "clientId",
                "claim.name": "clientId",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true"
            }
        },
        {
            "name": "acr loa level",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-acr-mapper",
            "config": {
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        },
        {
            "name": "family name",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "config": {
                "user.attribute": "lastName",
                "claim.name": "family_name",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true"
            }
        }
    ]

    for mapper in common_mappers:
        upsert_mapper(mappers_url, headers, existing_mappers, mapper)

def upsert_mapper(mappers_url, headers, existing_mappers, mapper_config):
    # Find by name
    existing = next((m for m in existing_mappers if m['name'] == mapper_config['name']), None)
    if existing:
        print(f"Updating mapper {mapper_config['name']}...")
        # Merge configuration to preserve ID and other fields
        updated_mapper = existing.copy()
        updated_mapper.update(mapper_config)
        # Ensure the ID matches the path
        updated_mapper['id'] = existing['id']
        requests.put(f"{mappers_url}/{existing['id']}", headers=headers, json=updated_mapper).raise_for_status()
    else:
        print(f"Creating mapper {mapper_config['name']}...")
        requests.post(mappers_url, headers=headers, json=mapper_config).raise_for_status()

def configure_scopes(base_url, realm, token, client_uuid):
    headers = get_headers(token)
    # Docs: Navigate to Client details -> Client Scopes. Remove "roles" scope.
    
    # Get assigned default client scopes
    default_scopes_url = f"{base_url}/admin/realms/{realm}/clients/{client_uuid}/default-client-scopes"
    response = requests.get(default_scopes_url, headers=headers)
    if response.status_code == 200:
        default_scopes = response.json()
        roles_scope = next((s for s in default_scopes if s['name'] == 'roles'), None)
        if roles_scope:
            print("Removing 'roles' from default client scopes...")
            requests.delete(f"{default_scopes_url}/{roles_scope['id']}", headers=headers).raise_for_status()

    # Get assigned optional client scopes
    optional_scopes_url = f"{base_url}/admin/realms/{realm}/clients/{client_uuid}/optional-client-scopes"
    response = requests.get(optional_scopes_url, headers=headers)
    if response.status_code == 200:
        optional_scopes = response.json()
        roles_scope_opt = next((s for s in optional_scopes if s['name'] == 'roles'), None)
        if roles_scope_opt:
            print("Removing 'roles' from optional client scopes...")
            requests.delete(f"{optional_scopes_url}/{roles_scope_opt['id']}", headers=headers).raise_for_status()

def main():
    print("Starting Keycloak Client Creation...")
    
    # Wait for Keycloak to be ready
    token = None
    for i in range(30):
        try:
            token = get_admin_token()
            if token:
                break
        except Exception:
            pass
        print("Waiting for Keycloak...")
        time.sleep(5)
    
    if not token:
        print("Could not connect to Keycloak.")
        sys.exit(1)

    # Read Input
    if not os.path.exists(INPUT_FILE):
        print(f"Input file {INPUT_FILE} not found.")
        sys.exit(1)

    with open(INPUT_FILE, 'r') as f:
        config = yaml.safe_load(f)

    clients = config.get('clients', [])
    for client_def in clients:
        # Construct base client config from params
        client_config = {
            "clientId": client_def['clientId'],
            "name": client_def.get('name', client_def['clientId']),
            "protocol": "openid-connect",
            "publicClient": False, # Client authentication: On
            "standardFlowEnabled": True, # Standard flow
            "serviceAccountsEnabled": True, # Service accounts roles
            "directAccessGrantsEnabled": False, # Disable Direct Access Grants
            "frontchannelLogout": True, # Enable Front Channel Logout
            "alwaysDisplayInConsole": True, # Always display in UI: On
            "redirectUris": client_def.get('redirectUris', ['*']),
            # Add secret if provided, otherwise Keycloak generates it
            # Docs say "note down the client ID and secret". 
            # If we want to set a specific secret (e.g. from GitOps), we can support it.
            # But usually for creation we let Keycloak generate it or we set it if provided.
        }
        # Check for mounted secret
        secret_file = f"/secrets/{client_def['clientId']}/client_secret"
        if os.path.exists(secret_file):
            print(f"Reading secret from {secret_file}")
            with open(secret_file, 'r') as f:
                client_config['secret'] = f.read().strip()
        elif 'secret' in client_def:
            client_config['secret'] = client_def['secret']
        
        create_client(KEYCLOAK_URL, KEYCLOAK_REALM, token, client_config)

if __name__ == "__main__":
    main()
