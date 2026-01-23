###
# Vereinfachte Variante nur für lokale Ausführung Python / Container (User Principals)
###
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from typing import Dict 

# --- OCI SDK Imports ---
import oci
from oci.generative_ai_agent_runtime.generative_ai_agent_runtime_client import GenerativeAiAgentRuntimeClient
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails
from oci.exceptions import ServiceError 

# --- Konfiguration ---
OCI_CONFIG_FILE_PATH = os.getenv("OCI_CONFIG_FILE_PATH", "~/.oci/config")
OCI_PROFILE = os.getenv("OCI_PROFILE", "DEFAULT") 
AGENT_ENDPOINT_ID = os.getenv("AGENT_ENDPOINT_ID") 

app = FastAPI()
agent_client: GenerativeAiAgentRuntimeClient = None

# --- OCI-Client Initialisierung ---
def initialize_agent_client():
    """Initialisiert den OCI GenerativeAiAgentRuntimeClient."""
    global agent_client
    
    if not AGENT_ENDPOINT_ID:
         print("KRITISCHER FEHLER: AGENT_ENDPOINT_ID (OCID des Agenten) ist nicht gesetzt.")
         return

    try:
        config = oci.config.from_file(file_location=OCI_CONFIG_FILE_PATH, profile_name=OCI_PROFILE)
        agent_client = GenerativeAiAgentRuntimeClient(config)
        print(f"OCI GenerativeAiAgentRuntimeClient erfolgreich initialisiert.")
    except Exception as e:
        print(f"KRITISCHER FEHLER: Initialisierung des OCI Client fehlgeschlagen. Fehler: {e}")
        agent_client = None

initialize_agent_client()

# BaseModel Definition
class ChatRequest(BaseModel):
    user_message: str
    session_id: str | None 

# Statische Dateien bereitstellen
app.mount("/static", StaticFiles(directory="static"), name="static")

## --- API-Endpunkte ---

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Liefert die statische HTML-Datei des Frontends aus."""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>Fehler: index.html nicht im Ordner 'static' gefunden.</h1>", status_code=404)


async def get_or_create_oci_session_id(current_session_id: str | None) -> str:
    """Überprüft die Session-ID. Wenn sie ungültig oder nicht vorhanden ist, wird eine neue erstellt."""
    global agent_client, AGENT_ENDPOINT_ID

    if current_session_id:
        return current_session_id
    
    try:
        create_details = CreateSessionDetails(
            display_name="ChatApp Session", 
            description="Session gestartet von FastAPI Backend"
        )
        
        create_response = agent_client.create_session(
            agent_endpoint_id=AGENT_ENDPOINT_ID,
            create_session_details=create_details
        )
        
        new_session_id = create_response.data.id
        return new_session_id

    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=f"OCI Session Erstellungsfehler: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unerwarteter Fehler bei der Session-Erstellung: {e}")


@app.post("/api/chat")
async def chat_with_agent(req: ChatRequest) -> Dict[str, str]:
    """Sendet die Chat-Anfrage und extrahiert nur den reinen Text."""
    
    if not agent_client:
        raise HTTPException(status_code=503, detail="Backend-Fehler: OCI Agent Client ist nicht initialisiert.")

    try:
        valid_oci_session_id = await get_or_create_oci_session_id(req.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler bei der Session-Verwaltung: {e}")

    try:
        # 1. Chat-Anfrage vorbereiten
        chat_details = ChatDetails(
            user_message=req.user_message,
            should_stream=False,
            session_id=valid_oci_session_id 
        )
        
        # 2. Chat-Anfrage senden
        chat_response = agent_client.chat(
            agent_endpoint_id=AGENT_ENDPOINT_ID,
            chat_details=chat_details
        )
        
        agent_answer = "Entschuldigung, der Agent konnte keine Textantwort liefern."
        
        if chat_response.data:
            agent_answer=str(chat_response.data.message.content.text)

        return {"answer": agent_answer, "session_id": valid_oci_session_id}

    except ServiceError as e:
        error_message = f"OCI Service Fehler: [{e.code}] {e.message}"
        print(f"DEBUG OCI ERROR: {error_message} (Status: {e.status})")
        raise HTTPException(status_code=e.status, detail=error_message)
        
    except Exception as err:
        print(f"Unerwarteter Chat-Fehler: {err}")
        raise HTTPException(status_code=500, detail=f"Unerwarteter Chat-Fehler: {err}")