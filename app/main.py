"""FastAPI gateway for the class ledger.

Every access decision is taken by the smart contract (view calls carry the
user's address as msg.sender). This layer only mirrors those rules for the UI
and turns contract reverts into friendly messages.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from web3 import Web3

from app import auth, files
from app.chain import contract_address, get_contract, get_w3, send_as_teacher

KIND_NAMES = ["Cours", "TP", "Examen", "Correction"]
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB is plenty for a demo document
CLASS_TIMEZONE = ZoneInfo(os.environ.get("CLASS_TIMEZONE", "Europe/Paris"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    auth.init_db()
    yield


app = FastAPI(title="Registre de classe — blockchain", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "dev"), same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def current_user(request: Request) -> dict | None:
    username = request.session.get("user")
    return auth.get_user(username) if username else None


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=ctx)


def materials_for(c, address: str) -> list[dict]:
    """Materials whose metadata the address may see, with the 24h lock state."""
    out = []
    for i in range(c.functions.materialCount().call()):
        try:
            kind, title, exam_at, has_prev, prev_id, accessible = c.functions.getMeta(i).call(
                {"from": address}
            )
        except Exception:
            continue  # not enrolled: cannot even list it
        out.append(
            {
                "id": i,
                "kind": KIND_NAMES[kind],
                "title": title,
                "exam_at": exam_at,
                "has_prev": has_prev,
                "prev_id": prev_id,
                "accessible": accessible,
            }
        )
    return out


# --- public ---


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = current_user(request)
    description = organization = None
    deployed = False
    try:
        w3 = get_w3()
        c = get_contract(w3)
        if c is not None:
            description = c.functions.classDescription().call()
            organization = c.functions.classOrganization().call()
            deployed = True
    except Exception:
        pass
    return render(
        request,
        "index.html",
        user=user,
        deployed=deployed,
        description=description,
        organization=organization,
    )


@app.get("/health")
def health():
    try:
        w3 = get_w3()
        address = contract_address()
        deployed = bool(
            address
            and w3.is_connected()
            and w3.eth.get_code(Web3.to_checksum_address(address))
        )
        return {"rpc": w3.is_connected(), "contract": address if deployed else None}
    except Exception:
        return {"rpc": False, "contract": None}


# --- auth ---


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html", error=None)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate(username, password)
    if not user:
        return render(request, "login.html", error="Identifiants invalides")
    request.session["user"] = user["username"]
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# --- dashboard ---


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    c = get_contract(get_w3())
    if c is None:
        return render(request, "not_deployed.html", user=user)

    if user["role"] == "teacher":
        addr = Web3.to_checksum_address(user["address"])
        students = []
        for i in range(c.functions.studentCount().call({"from": addr})):
            s = c.functions.studentAt(i).call({"from": addr})
            published, value = c.functions.gradeOf(s).call({"from": addr})
            students.append({"address": s, "published": published, "grade": value})
        return render(
            request,
            "teacher.html",
            user=user,
            materials=materials_for(c, addr),
            students=students,
            kinds=list(enumerate(KIND_NAMES)),
        )

    addr = Web3.to_checksum_address(user["address"])
    enrolled = c.functions.isEnrolled(addr).call()
    published, grade = c.functions.myGrade().call({"from": addr})
    return render(
        request,
        "student.html",
        user=user,
        enrolled=enrolled,
        materials=materials_for(c, addr) if enrolled else [],
        published=published,
        grade=grade,
    )


# --- teacher actions ---


@app.post("/enroll")
def enroll(request: Request, address: str = Form(...)):
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    w3 = get_w3()
    c = get_contract(w3)
    try:
        send_as_teacher(w3, c.functions.enroll(Web3.to_checksum_address(address)))
    except Exception as exc:
        return render(request, "error.html", user=user, message=f"Inscription refusée : {exc}")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/material")
async def add_material(
    request: Request,
    kind: int = Form(...),
    title: str = Form(...),
    exam_at: str = Form(""),
    prev_id: str = Form(""),
    file: UploadFile = File(...),
):
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        return render(request, "error.html", user=user, message="Fichier trop volumineux (max 10 Mo).")
    try:
        exam_ts = (
            int(datetime.fromisoformat(exam_at).replace(tzinfo=CLASS_TIMEZONE).timestamp())
            if exam_at
            else 0
        )
        has_prev = prev_id.strip() != ""
        pid = int(prev_id) if has_prev else 0
    except ValueError:
        return render(request, "error.html", user=user, message="Date ou numéro de version invalide.")
    ref, digest = files.save(data, file.filename or "document")
    w3 = get_w3()
    c = get_contract(w3)
    try:
        send_as_teacher(
            w3, c.functions.addMaterial(kind, title, ref, digest, exam_ts, has_prev, pid)
        )
    except Exception as exc:
        files.delete(ref)  # keep disk and chain consistent
        return render(request, "error.html", user=user, message=f"Transaction refusée : {exc}")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/grade")
def publish_grade(request: Request, address: str = Form(...), value: str = Form(...)):
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    w3 = get_w3()
    c = get_contract(w3)
    try:
        send_as_teacher(w3, c.functions.publishGrade(Web3.to_checksum_address(address), value))
    except Exception as exc:
        return render(request, "error.html", user=user, message=f"Publication refusée : {exc}")
    return RedirectResponse("/dashboard", status_code=303)


# --- file download (contract-gated) ---


@app.get("/material/{material_id}/download")
def download(request: Request, material_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    c = get_contract(get_w3())
    try:
        ref, file_hash = c.functions.getFile(material_id).call(
            {"from": Web3.to_checksum_address(user["address"])}
        )
    except Exception:
        return render(request, "error.html", user=user, message="Accès refusé à ce document.")
    data = files.read(ref)
    if data is None:
        return render(request, "error.html", user=user, message="Fichier introuvable sur le serveur.")
    if files.sha256(data) != bytes(file_hash):
        return render(request, "error.html", user=user, message="Intégrité du fichier compromise.")
    filename = ref.split("_", 1)[1] if "_" in ref else ref
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- proof view ---


@app.get("/proof", response_class=HTMLResponse)
def proof(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    w3 = get_w3()
    info = {"connected": False, "chain_id": None, "block": None, "peers": None, "validators": []}
    try:
        info["connected"] = w3.is_connected()
        info["chain_id"] = w3.eth.chain_id
        info["block"] = w3.eth.block_number
        info["peers"] = int(w3.net.peer_count)
        info["validators"] = list(w3.manager.request_blocking("qbft_getValidatorsByBlockNumber", ["latest"]))
    except Exception:
        pass
    info["address"] = contract_address()
    return render(request, "proof.html", user=user, info=info)
