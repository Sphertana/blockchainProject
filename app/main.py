"""FastAPI gateway for the class ledger.

Every access decision is taken by the smart contract (view calls carry the
user's address as msg.sender). This layer only mirrors those rules for the UI
and turns contract reverts into friendly messages.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from web3 import Web3

from app import auth, files, grade_crypto, security
from app.chain import contract_address, get_contract, get_w3, send_as, send_as_teacher

KIND_NAMES = ["Cours", "TP", "Examen", "Correction"]
STATUS_NAMES = ["none", "pending", "enrolled", "rejected"]
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB is plenty for a demo document
CLASS_TIMEZONE = ZoneInfo(os.environ.get("CLASS_TIMEZONE", "Europe/Paris"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    security.validate_runtime()
    auth.init_db()
    yield


PRODUCTION = os.environ.get("ENVIRONMENT", "development") == "production"
app = FastAPI(
    title="Registre de classe — blockchain",
    lifespan=lifespan,
    docs_url=None if PRODUCTION else "/docs",
    redoc_url=None if PRODUCTION else "/redoc",
    openapi_url=None if PRODUCTION else "/openapi.json",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev"),
    same_site="strict",
    https_only=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
    max_age=2 * 60 * 60,
)
allowed_hosts = ["localhost", "127.0.0.1"]
if os.environ.get("PUBLIC_HOST"):
    allowed_hosts.append(os.environ["PUBLIC_HOST"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if os.environ.get("COOKIE_SECURE", "false").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _fmt(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(CLASS_TIMEZONE).strftime("%d/%m/%Y %H:%M")


templates.env.filters["dt"] = _fmt


def current_user(request: Request) -> dict | None:
    username = request.session.get("user")
    return auth.get_user(username) if username else None


def flash(request: Request, message: str, level: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"level": level, "text": message})


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx["messages"] = request.session.pop("flash", [])
    ctx["csrf_token"] = security.csrf_token(request)
    return templates.TemplateResponse(request=request, name=name, context=ctx)


def back(request: Request, message: str, level: str = "ok", to: str = "/dashboard"):
    flash(request, message, level)
    return RedirectResponse(to, status_code=303)


def revert_reason(exc: Exception) -> str:
    """Surface the contract's own `require` message, not a stack of hex."""
    text = str(exc)
    for marker in ("execution reverted: ", "revert "):
        if marker in text:
            return text.split(marker, 1)[1].strip(" '\"")
    return text


def materials_for(c, address: str) -> list[dict]:
    """Materials whose metadata the address may see, with the 24h lock state."""
    out = []
    for i in range(c.functions.materialCount().call()):
        try:
            kind, title, exam_at, has_prev, prev_id, accessible, created_at = c.functions.getMeta(i).call(
                {"from": address}
            )
        except Exception:
            continue  # not enrolled: cannot even list it
        out.append(
            {
                "id": i,
                "kind": KIND_NAMES[kind],
                "kind_id": kind,
                "title": title,
                "exam_at": exam_at,
                "unlocks_at": exam_at + 24 * 3600 if exam_at else 0,
                "created_at": created_at,
                "has_prev": has_prev,
                "prev_id": prev_id,
                "accessible": accessible,
            }
        )
    out.reverse()  # newest first
    return out


# --- public ---


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = current_user(request)
    description = organization = None
    deployed = False
    stats = {"materials": None, "students": None, "block": None}
    try:
        w3 = get_w3()
        c = get_contract(w3)
        if c is not None:
            description = c.functions.classDescription().call()
            organization = c.functions.classOrganization().call()
            stats = {
                "materials": c.functions.materialCount().call(),
                "students": c.functions.studentCount().call(),
                "block": w3.eth.block_number,
            }
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
        stats=stats,
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
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
):
    security.require_csrf(request, csrf_token)
    security.rate_limiter.enforce(security.client_key(request, "login"), 10, 5 * 60)
    user = auth.authenticate(username, password)
    if not user:
        return render(request, "login.html", error="Identifiants invalides")
    request.session.clear()
    request.session["user"] = user["username"]
    security.csrf_token(request)
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "register.html", error=None, username="")


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    csrf_token: str = Form(""),
):
    security.require_csrf(request, csrf_token)
    security.rate_limiter.enforce(security.client_key(request, "register"), 5, 10 * 60)
    try:
        user = auth.register(username, password, confirm)
    except auth.RegistrationError as exc:
        return render(request, "register.html", error=str(exc), username=username)
    request.session.clear()
    request.session["user"] = user["username"]
    security.csrf_token(request)
    flash(
        request,
        "Compte créé. Un portefeuille blockchain vous a été attribué : "
        "demandez maintenant votre inscription à la classe.",
    )
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    security.require_csrf(request, csrf_token)
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
    addr = Web3.to_checksum_address(user["address"])

    if user["role"] == "teacher":
        names = auth.names_by_address()
        pending = [
            {"address": a, "name": names.get(a), "at": c.functions.appliedAt(a).call()}
            for a in c.functions.pendingApplicants().call({"from": addr})
        ]
        students = []
        for s in c.functions.enrolledStudents().call({"from": addr}):
            published, value = c.functions.gradeOf(s).call({"from": addr})
            if published:
                try:
                    value = grade_crypto.decrypt_grade(s, value)
                except ValueError:
                    value = "Indisponible (intégrité invalide)"
            students.append(
                {"address": s, "name": names.get(s), "published": published, "grade": value}
            )
        return render(
            request,
            "teacher.html",
            user=user,
            materials=materials_for(c, addr),
            pending=pending,
            students=students,
            kinds=list(enumerate(KIND_NAMES)),
        )

    status = STATUS_NAMES[c.functions.statusOf(addr).call()]
    enrolled = status == "enrolled"
    published, grade = c.functions.myGrade().call({"from": addr})
    if published:
        try:
            grade = grade_crypto.decrypt_grade(addr, grade)
        except ValueError:
            grade = "Indisponible (intégrité invalide)"
    return render(
        request,
        "student.html",
        user=user,
        status=status,
        applied_at=c.functions.appliedAt(addr).call(),
        enrolled=enrolled,
        materials=materials_for(c, addr) if enrolled else [],
        published=published,
        grade=grade,
    )


# --- enrollment workflow ---


@app.post("/enrollment/request")
def request_enrollment(request: Request, csrf_token: str = Form("")):
    security.require_csrf(request, csrf_token)
    user = current_user(request)
    if not user or user["role"] != "student":
        return RedirectResponse("/login", status_code=303)
    w3 = get_w3()
    c = get_contract(w3)
    try:
        send_as(w3, c.functions.requestEnrollment(), auth.private_key(user["username"]))
    except Exception as exc:
        return back(request, f"Demande refusée : {revert_reason(exc)}", "error")
    return back(request, "Demande envoyée et inscrite dans un bloc. En attente de l'enseignant.")


@app.post("/enrollment/decide")
def decide_enrollment(
    request: Request,
    address: str = Form(...),
    action: str = Form(...),
    csrf_token: str = Form(""),
):
    security.require_csrf(request, csrf_token)
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    if action not in ("approve", "reject"):
        return back(request, "Action inconnue.", "error")
    w3 = get_w3()
    c = get_contract(w3)
    try:
        student = Web3.to_checksum_address(address)
        fn = (
            c.functions.approveEnrollment(student)
            if action == "approve"
            else c.functions.rejectEnrollment(student)
        )
        send_as_teacher(w3, fn)
    except ValueError:
        return back(request, "Adresse Ethereum invalide.", "error")
    except Exception as exc:
        return back(request, f"Décision refusée : {revert_reason(exc)}", "error")
    return back(request, "Étudiant inscrit." if action == "approve" else "Demande rejetée.")


# --- teacher actions ---


@app.post("/material")
async def add_material(
    request: Request,
    kind: int = Form(...),
    title: str = Form(...),
    exam_at: str = Form(""),
    prev_id: str = Form(""),
    file: UploadFile = File(...),
    csrf_token: str = Form(""),
):
    security.require_csrf(request, csrf_token)
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return back(request, "Fichier trop volumineux (max 10 Mo).", "error")
    title = title.strip()
    if not title or len(title) > 120:
        return back(request, "Le titre doit contenir entre 1 et 120 caractères.", "error")
    if kind not in range(len(KIND_NAMES)):
        return back(request, "Type de document invalide.", "error")
    if not data:
        return back(request, "Le fichier est vide.", "error")
    try:
        exam_ts = (
            int(datetime.fromisoformat(exam_at).replace(tzinfo=CLASS_TIMEZONE).timestamp())
            if exam_at
            else 0
        )
        has_prev = prev_id.strip() != ""
        pid = int(prev_id) if has_prev else 0
        if pid < 0:
            raise ValueError
    except ValueError:
        return back(request, "Date ou numéro de version invalide.", "error")
    ref, digest = files.save(data, file.filename or "document")
    w3 = get_w3()
    c = get_contract(w3)
    try:
        send_as_teacher(
            w3, c.functions.addMaterial(kind, title, ref, digest, exam_ts, has_prev, pid)
        )
    except Exception as exc:
        files.delete(ref)  # keep disk and chain consistent
        return back(request, f"Transaction refusée : {revert_reason(exc)}", "error")
    return back(request, f"« {title} » publié sur la blockchain.")


@app.post("/grade")
def publish_grade(
    request: Request,
    address: str = Form(...),
    value: str = Form(...),
    csrf_token: str = Form(""),
):
    security.require_csrf(request, csrf_token)
    user = current_user(request)
    if not user or user["role"] != "teacher":
        return RedirectResponse("/login", status_code=303)
    value = value.strip()
    if not value or len(value) > 32:
        return back(request, "La note doit contenir entre 1 et 32 caractères.", "error")
    w3 = get_w3()
    c = get_contract(w3)
    try:
        student = Web3.to_checksum_address(address)
        encrypted = grade_crypto.encrypt_grade(student, value)
        send_as_teacher(w3, c.functions.publishGrade(student, encrypted))
    except ValueError:
        return back(request, "Adresse Ethereum invalide.", "error")
    except Exception as exc:
        return back(request, f"Publication refusée : {revert_reason(exc)}", "error")
    return back(request, "Note publiée (visible uniquement par cet étudiant).")


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
