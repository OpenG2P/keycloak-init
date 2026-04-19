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

def ensure_realm(base_url, token, realm_name):
    """Create a realm if it does not already exist. Skip if it exists."""
    headers = get_headers(token)
    realm_url = f"{base_url}/admin/realms/{realm_name}"
    response = requests.get(realm_url, headers=headers)
    if response.status_code == 200:
        print(f"Realm '{realm_name}' already exists. Skipping creation.")
        return
    if response.status_code == 404:
        print(f"Creating realm '{realm_name}'...")
        create_url = f"{base_url}/admin/realms"
        payload = {
            "realm": realm_name,
            "enabled": True
        }
        requests.post(create_url, headers=headers, json=payload).raise_for_status()
        print(f"Realm '{realm_name}' created successfully.")
        return
    response.raise_for_status()

def configure_themes(base_url, token, realm_name, theme_config):
    """Apply login and/or admin themes to a realm."""
    if not theme_config:
        return

    headers = get_headers(token)
    realm_url = f"{base_url}/admin/realms/{realm_name}"

    payload = {}
    if 'loginTheme' in theme_config:
        payload['loginTheme'] = theme_config['loginTheme']
    if 'adminTheme' in theme_config:
        payload['adminTheme'] = theme_config['adminTheme']

    if not payload:
        return

    # Check current themes to avoid unnecessary updates
    response = requests.get(realm_url, headers=headers)
    response.raise_for_status()
    current = response.json()

    needs_update = False
    for key, value in payload.items():
        if current.get(key) != value:
            needs_update = True
            break

    if not needs_update:
        print(f"Themes for realm '{realm_name}' already set. Skipping.")
        return

    print(f"Applying themes to realm '{realm_name}': {payload}")
    current.update(payload)
    requests.put(realm_url, headers=headers, json=current).raise_for_status()
    print(f"Themes for realm '{realm_name}' applied successfully.")

def configure_users(base_url, token, realm_name, users):
    """Create users and assign roles. Skip if user already exists."""
    if not users:
        return

    for user_def in users:
        username = user_def['username']
        user_id = ensure_user(base_url, token, realm_name, user_def)
        if not user_id:
            continue

        # Assign realm roles
        realm_roles = user_def.get('realmRoles', [])
        if realm_roles:
            assign_realm_roles(base_url, token, realm_name, user_id, realm_roles)

        # Assign client roles
        client_role_mappings = user_def.get('clientRoleMappings', {})
        for client_id_name, role_names in client_role_mappings.items():
            assign_client_roles_to_user(
                base_url, token, realm_name, user_id, client_id_name, role_names
            )

def ensure_user(base_url, token, realm_name, user_def):
    """Create a user if not exists. Returns user ID."""
    headers = get_headers(token)
    username = user_def['username']
    users_url = f"{base_url}/admin/realms/{realm_name}/users"

    # Check if user exists
    response = requests.get(users_url, headers=headers, params={'username': username, 'exact': 'true'})
    response.raise_for_status()
    existing = response.json()
    if existing:
        print(f"User '{username}' already exists. Skipping creation.")
        return existing[0]['id']

    # Cannot create without a password
    if 'password' not in user_def:
        print(f"User '{username}' does not exist and no password provided. Skipping.")
        return None

    # Create user
    print(f"Creating user '{username}'...")
    payload = {
        "username": username,
        "email": user_def.get('email', ''),
        "emailVerified": True,
        "enabled": True,
        "credentials": [{
            "type": "password",
            "value": user_def['password'],
            "temporary": True
        }],
        "requiredActions": ["UPDATE_PASSWORD"]
    }
    response = requests.post(users_url, headers=headers, json=payload)
    response.raise_for_status()

    # Get user ID from Location header or by querying
    location = response.headers.get('Location', '')
    if location:
        user_id = location.split('/')[-1]
    else:
        resp = requests.get(users_url, headers=headers, params={'username': username, 'exact': 'true'})
        resp.raise_for_status()
        user_id = resp.json()[0]['id']

    print(f"User '{username}' created successfully.")
    return user_id

def assign_realm_roles(base_url, token, realm_name, user_id, role_names):
    """Assign realm-level roles to a user."""
    headers = get_headers(token)
    roles_url = f"{base_url}/admin/realms/{realm_name}/roles"
    mapping_url = f"{base_url}/admin/realms/{realm_name}/users/{user_id}/role-mappings/realm"

    # Get existing realm role assignments
    response = requests.get(mapping_url, headers=headers)
    existing_roles = {r['name'] for r in response.json()} if response.status_code == 200 else set()

    roles_to_add = []
    for role_name in role_names:
        if role_name in existing_roles:
            print(f"User already has realm role '{role_name}'. Skipping.")
            continue
        resp = requests.get(f"{roles_url}/{role_name}", headers=headers)
        if resp.status_code == 200:
            roles_to_add.append(resp.json())
        else:
            print(f"Warning: realm role '{role_name}' not found. Skipping.")

    if roles_to_add:
        print(f"Assigning {len(roles_to_add)} realm role(s)...")
        requests.post(mapping_url, headers=headers, json=roles_to_add).raise_for_status()

def assign_client_roles_to_user(base_url, token, realm_name, user_id, client_id_name, role_names):
    """Assign client-level roles to a user."""
    headers = get_headers(token)

    # Look up client UUID
    clients_url = f"{base_url}/admin/realms/{realm_name}/clients"
    response = requests.get(clients_url, headers=headers, params={'clientId': client_id_name})
    response.raise_for_status()
    clients = response.json()
    if not clients:
        print(f"Warning: client '{client_id_name}' not found. Skipping role assignment.")
        return
    client_uuid = clients[0]['id']

    mapping_url = (
        f"{base_url}/admin/realms/{realm_name}/users/{user_id}"
        f"/role-mappings/clients/{client_uuid}"
    )

    # Get existing client role assignments
    response = requests.get(mapping_url, headers=headers)
    existing_roles = {r['name'] for r in response.json()} if response.status_code == 200 else set()

    client_roles_url = f"{base_url}/admin/realms/{realm_name}/clients/{client_uuid}/roles"
    roles_to_add = []
    for role_name in role_names:
        if role_name in existing_roles:
            print(f"User already has client role '{role_name}' on '{client_id_name}'. Skipping.")
            continue
        resp = requests.get(f"{client_roles_url}/{role_name}", headers=headers)
        if resp.status_code == 200:
            roles_to_add.append(resp.json())
        else:
            print(f"Warning: client role '{role_name}' on '{client_id_name}' not found. Skipping.")

    if roles_to_add:
        print(f"Assigning {len(roles_to_add)} client role(s) from '{client_id_name}'...")
        requests.post(mapping_url, headers=headers, json=roles_to_add).raise_for_status()

def create_client(base_url, realm, token, client_config, client_roles=None):
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

    # 3. Configure Client Roles
    configure_client_roles(base_url, realm, token, client_uuid, client_roles)

    # 4. Retain "roles" scope (Logic to remove it is now removed)
    # configure_scopes(base_url, realm, token, client_uuid)

    print(f"Client {client_id} processed successfully.")

def configure_client_roles(base_url, realm, token, client_uuid, roles):
    if not roles:
        return

    headers = get_headers(token)
    roles_url = f"{base_url}/admin/realms/{realm}/clients/{client_uuid}/roles"

    # First pass: create all roles
    composite_definitions = []
    for role_entry in roles:
        if isinstance(role_entry, str):
            role_name = role_entry
        elif isinstance(role_entry, dict):
            role_name = role_entry['name']
            if 'composites' in role_entry:
                composite_definitions.append(role_entry)
        else:
            print(f"Skipping invalid role entry: {role_entry}")
            continue

        print(f"Creating client role '{role_name}'...")
        role_payload = {"name": role_name}
        try:
            requests.post(roles_url, headers=headers, json=role_payload).raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                print(f"Role '{role_name}' already exists.")
            else:
                print(f"Failed to create role '{role_name}': {e}")
                raise

    # Second pass: configure composite roles
    for comp_entry in composite_definitions:
        configure_composite_role(base_url, realm, token, client_uuid, comp_entry)

def configure_composite_role(base_url, realm, token, client_uuid, comp_entry):
    """Make a client role composite by adding child roles to it."""
    headers = get_headers(token)
    role_name = comp_entry['name']
    child_names = comp_entry.get('composites', [])
    if not child_names:
        return

    composites_url = (
        f"{base_url}/admin/realms/{realm}/clients/{client_uuid}"
        f"/roles/{role_name}/composites"
    )

    # Get existing composites to avoid duplicates
    response = requests.get(composites_url, headers=headers)
    if response.status_code == 200:
        existing_composites = {r['name'] for r in response.json()}
    else:
        existing_composites = set()

    # Look up full role representations for children not yet added
    roles_to_add = []
    for child_name in child_names:
        if child_name in existing_composites:
            print(f"Composite '{role_name}' already contains '{child_name}'. Skipping.")
            continue
        role_url = (
            f"{base_url}/admin/realms/{realm}/clients/{client_uuid}"
            f"/roles/{child_name}"
        )
        resp = requests.get(role_url, headers=headers)
        if resp.status_code == 200:
            roles_to_add.append(resp.json())
        else:
            print(f"Warning: child role '{child_name}' not found. Skipping.")

    if roles_to_add:
        print(f"Adding {len(roles_to_add)} child role(s) to composite '{role_name}'...")
        requests.post(composites_url, headers=headers, json=roles_to_add).raise_for_status()
        print(f"Composite role '{role_name}' configured successfully.")

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

    realms = config.get('realms', {})
    for realm_name, realm_def in realms.items():
        print(f"\n--- Processing realm: {realm_name} ---")
        ensure_realm(KEYCLOAK_URL, token, realm_name)

        # Apply themes if specified
        themes = realm_def.get('themes') if realm_def else None
        configure_themes(KEYCLOAK_URL, token, realm_name, themes)

        clients = realm_def.get('clients', []) if realm_def else []
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
            }
            # Check for mounted secret
            secret_file = f"/secrets/{client_def['clientId']}/client_secret"
            if os.path.exists(secret_file):
                print(f"Reading secret from {secret_file}")
                with open(secret_file, 'r') as f:
                    client_config['secret'] = f.read().strip()
            elif 'secret' in client_def:
                client_config['secret'] = client_def['secret']

            client_roles = client_def.get('clientRoles', [])
            create_client(KEYCLOAK_URL, realm_name, token, client_config, client_roles)

        # Create users after clients and roles are in place
        users = realm_def.get('users', []) if realm_def else []
        configure_users(KEYCLOAK_URL, token, realm_name, users)

if __name__ == "__main__":
    main()
