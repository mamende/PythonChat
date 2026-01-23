###
# Variante die Ausführung als COntainer Instance (Resource Principals)
###
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from typing import Dict, Optional
# --- OCI SDK Imports ---
import oci
import oci.auth
from oci.generative_ai_agent_runtime.models import ChatDetails, CreateSessionDetails
from oci.exceptions import ServiceError
from oci.generative_ai_agent_runtime import GenerativeAiAgentRuntimeClient

# --- Konfiguration ---
AGENT_ENDPOINT_ID = os.getenv("AGENT_ENDPOINT_ID")
app = FastAPI()
agent_client: Optional[GenerativeAiAgentRuntimeClient] = None

# --- OCI-Client Initialisierung ---
def initialize_agent_client():
    """Initialisiert den OCI GenerativeAiAgentRuntimeClient (Resource Principals)."""
    global agent_client

    if not AGENT_ENDPOINT_ID:
        print("KRITISCHER FEHLER: AGENT_ENDPOINT_ID (OCID des Agenten) ist nicht gesetzt.")
        agent_client = None
        return
    try:
        print("Init signer: Resource Principals")
        signer = oci.auth.signers.get_resource_principals_signer()
        agent_client = GenerativeAiAgentRuntimeClient(
            config={},          # leer bei Resource Principals
            signer=signer,
            region="eu-frankfurt-1"
        )
        print("OCI GenerativeAiAgentRuntimeClient erfolgreich mit Resource Principals initialisiert.")
    except Exception as e:
        print(f"KRITISCHER FEHLER: Initialisierung des OCI Client fehlgeschlagen. Fehler: {e}")
        agent_client = None

initialize_agent_client()

# --- Helpers für Fehlerbehandlung ---
def _is_session_not_found(e: ServiceError) -> bool:
    """Erkennt abgelaufene/ungültige genaiagentsession (404/NotFound)."""
    if getattr(e, "status", None) == 404:
        return True
    code = (getattr(e, "code", "") or "").lower()
    msg = (getattr(e, "message", "") or "").lower()
    return ("notfound" in code or "notauthorizedornotfound" in code) and "genaiagentsession" in msg

def _is_auth_error(e: ServiceError) -> bool:
    """Erkennt Auth-Fehler (401/403 oder typische Meldungen)."""
    if getattr(e, "status", None) in (401, 403):
        return True
    code = (getattr(e, "code", "") or "").lower()
    msg = (getattr(e, "message", "") or "").lower()
    return ("notauthenticated" in code
            or "required information to complete authentication" in msg
            or "authentication was not provided" in msg
            or "signature does not match" in msg)

def _reinit_client():
    """Re-initialisiert den Client (z. B. nach Auth-Timeout)."""
    initialize_agent_client()
    if not agent_client:
        raise HTTPException(status_code=503, detail="OCI Agent Client konnte nicht reinitialisiert werden.")

# BaseModel Definition
class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str] = None

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

async def get_or_create_oci_session_id(current_session_id: Optional[str]) -> str:
    """Gibt eine gültige Session-ID zurück. Wenn keine vorhanden ist, wird eine neue erstellt (mit Auth-Retry)."""
    global agent_client, AGENT_ENDPOINT_ID
    if current_session_id:
        return current_session_id

    # Versuch 1
    try:
        create_details = CreateSessionDetails(
            display_name="ChatApp Session",
            description="Session gestartet von FastAPI Backend"
        )
        create_response = agent_client.create_session(
            agent_endpoint_id=AGENT_ENDPOINT_ID,
            create_session_details=create_details
        )
        return create_response.data.id
    except ServiceError as e:
        # Bei Auth-Fehler: Client re-initialisieren und einmal wiederholen
        if _is_auth_error(e):
            try:
                _reinit_client()
                create_details = CreateSessionDetails(
                    display_name="ChatApp Session",
                    description="Session gestartet von FastAPI Backend (retry)"
                )
                create_response = agent_client.create_session(
                    agent_endpoint_id=AGENT_ENDPOINT_ID,
                    create_session_details=create_details
                )
                return create_response.data.id
            except ServiceError as e2:
                raise HTTPException(status_code=e2.status, detail=f"OCI Session Erstellungsfehler: {e2.message}")
        raise HTTPException(status_code=e.status, detail=f"OCI Session Erstellungsfehler: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unerwarteter Fehler bei der Session-Erstellung: {e}")

@app.post("/api/chat")
async def chat_with_agent(req: ChatRequest) -> Dict[str, str]:
    """Sendet die Chat-Anfrage und extrahiert nur den reinen Text, inkl. Session/Auth-Retry."""
    global agent_client, AGENT_ENDPOINT_ID

    if not agent_client:
        raise HTTPException(status_code=503, detail="Backend-Fehler: OCI Agent Client ist nicht initialisiert.")
    try:
        valid_oci_session_id = await get_or_create_oci_session_id(req.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler bei der Session-Verwaltung: {e}")

    def _do_chat(session_id: str):
        chat_details = ChatDetails(
            user_message=req.user_message,
            should_stream=False,
            session_id=session_id
        )
        return agent_client.chat(
            agent_endpoint_id=AGENT_ENDPOINT_ID,
            chat_details=chat_details
        )

    # Erster Versuch
    try:
        chat_response = _do_chat(valid_oci_session_id)
    except ServiceError as e:
        # Session abgelaufen/ungültig -> neue Session erzeugen und einmalig wiederholen
        if _is_session_not_found(e):
            try:
                new_session_id = await get_or_create_oci_session_id(None)
                chat_response = _do_chat(new_session_id)
                valid_oci_session_id = new_session_id
            except ServiceError as e2:
                error_message = f"OCI Service Fehler (nach Session-Neuerstellung): [{e2.code}] {e2.message}"
                print(f"DEBUG OCI ERROR: {error_message} (Status: {e2.status})")
                raise HTTPException(status_code=e2.status, detail=error_message)
        # Auth-Problem -> Client re-init und einmalig wiederholen
        elif _is_auth_error(e):
            try:
                _reinit_client()
                chat_response = _do_chat(valid_oci_session_id)
            except ServiceError as e2:
                # Falls Session inzwischen abgelaufen ist, neuer Versuch mit neuer Session
                if _is_session_not_found(e2):
                    try:
                        new_session_id = await get_or_create_oci_session_id(None)
                        chat_response = _do_chat(new_session_id)
                        valid_oci_session_id = new_session_id
                    except ServiceError as e3:
                        error_message = f"OCI Service Fehler (nach Auth-Reinit + Session-Neu): [{e3.code}] {e3.message}"
                        print(f"DEBUG OCI ERROR: {error_message} (Status: {e3.status})")
                        raise HTTPException(status_code=e3.status, detail=error_message)
                else:
                    error_message = f"OCI Service Fehler (nach Auth-Reinit): [{e2.code}] {e2.message}"
                    print(f"DEBUG OCI ERROR: {error_message} (Status: {e2.status})")
                    raise HTTPException(status_code=e2.status, detail=error_message)
        else:
            error_message = f"OCI Service Fehler: [{e.code}] {e.message}"
            print(f"DEBUG OCI ERROR: {error_message} (Status: {e.status})")
            raise HTTPException(status_code=e.status, detail=error_message)
    except Exception as err:
        print(f"Unerwarteter Chat-Fehler: {err}")
        raise HTTPException(status_code=500, detail=f"Unerwarteter Chat-Fehler: {err}")

    agent_answer = "Entschuldigung, der Agent konnte keine Textantwort liefern."
    if chat_response.data:
        agent_answer = str(chat_response.data.message.content.text)
    return {"answer": agent_answer, "session_id": valid_oci_session_id}