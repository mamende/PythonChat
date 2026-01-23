### PythonChat
OCI AI Agent Web Client Example

### Kurzanleitung

## OCI Konfiguration bei lokaler Ausführung (main_localonly.py)
# Beispiel OCI Profil (in ~/.oci/config)
[WS]
user=ocid1.user.oc1..aaaaaaa...
fingerprint=9f:7d:f5:14:c3:...
tenancy=ocid1.tenancy.oc1..aaaaaaa...
region=eu-frankfurt-1
key_file=~/.oci/oci_api_key.pem

# Nutzen des Profils:
export OCI_CLI_PROFILE=WS

# Beispiel OCI API:
oci os ns get
{
  "data": "..."
}

## Python Konfiguration für lokale Ausführung
# Prepate a local Python Env, Install, Start (Mac)
python -m venv venv            
source venv/bin/activate  
pip install -r requirements.txt

# Environment variable for local app execution (Mac)
export OCI_CONFIG_FILE_PATH="/Users/.../.oci/config" 
export OCI_PROFILE="WS"

# Local app execution (Mac)
cd app
uvicorn main_localonly:app --reload --host 0.0.0.0 --port 8000

# Aufruf im Browser
http://127.0.0.1:8000/

## Lokale Ausführung als Container (main_localonly.py)
# Stoppen und entfernen des alten Containers
docker stop chat-agent-instance
docker rm chat-agent-instance

# Anpassung OCI Profil für Key File mount in Container
[CONTAINER]
user=ocid1.user.oc1..aaaaaaaa...
fingerprint=9f:7d:f5:14:c3:...
key_file=/root/.oci/oci_api_key.pem
tenancy=ocid1.tenancy.oc1..aaaaaaaa...
region=eu-frankfurt-1

export OCI_PROFILE="CONTAINER"

# Container bauen und starten
docker buildx build --platform linux/amd64 -t chat-agent-app:latest .

docker run -d --name chat-agent-instance -p 8000:8000 -e AGENT_ENDPOINT_ID='ocid1.genaiagentendpoint.oc1.eu-frankfurt-1.amaaaaaa...' -v ~/.oci:/root/.oci -e OCI_CONFIG_FILE_PATH='/root/.oci/config' -e OCI_PROFILE='CONTAINER' chat-agent-app:latest

# Aufruf im Browser
http://127.0.0.1:8000/

# Debug
docker ps
docker logs chat-agent-instance

## Container in OCI Registry pushen
docker login -u '<tenancy_ns>>/<user>' -p '<token>' fra.ocir.io
docker tag chat-agent-app fra.ocir.io/<ns>/chatagent:pychat
docker push fra.ocir.io/<ns>/chatagent:pychat

## Container als Container Instances deployen (main.py)
# dynamic group ContainerInstanceDynamicGroup/ContainerInstances
ALL {resource.type='computecontainerinstance'}

# policy (tenancy=weit offen!)
Allow dynamic-group ContainerInstances to read repos in tenancy
Allow dynamic-group ContainerInstances to manage genai-agent-family in tenancy

# Container Instance Konfiguration
Shape: x86 Prozessor (bei buildx)
Netzwerk: private subnet
Umgebungsvariable: AGENT_ENDPOINT_ID ocid1.genaiagentendpoint.oc1.eu-frankfurt-1.amaaaaaa...

Zugriff über Load Balancer in Public Subnet!