from flask import Flask, session, redirect, url_for, request, render_template, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
import firebase_admin
from firebase_admin import credentials, firestore
import json
import threading
from main import main as run_main
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import sys


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --- KHỞI TẠO FIREBASE ---
firebase_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
if not firebase_json:
    raise Exception("⚠️ FIREBASE_SERVICE_ACCOUNT_JSON không được thiết lập!")
cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

ADMIN_EMAIL = "danthi.nguyen@spxexpress.com"

SOC_CONFIG = {
    "bda": {
        "name": "BD A Mega SOC",
        "sheet_id": "1pLGWEeKRL57_36IUJWzHN2IzuanpL8jMZVhMdeHXLiw",
    },
    "bdb": {
        "name": "BD B Mega SOC",
        "sheet_id": "1OKJOftAkcmTtmO1w08V9sI1D3TWFusZP77SUfMpGSsM",
    },
}

def lock_ref(soc: str):
    return db.collection("locks").document(soc)

def read_lock(soc: str):
    doc = lock_ref(soc).get()
    if not doc.exists:
        return {"running": False, "message": "Chưa chạy", "by": None}
    d = doc.to_dict() or {}
    return {
        "running": bool(d.get("is_running", False)),
        "message": d.get("message", "Chưa chạy"),
        "by": d.get("by"),
    }

def acquire_lock(soc: str, user_email: str):
    ref = lock_ref(soc)

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        if snap.exists:
            d = snap.to_dict() or {}
            if d.get("is_running") and d.get("by") != user_email:
                return False, d.get("by"), d.get("message")
        txn.set(ref, {
            "is_running": True,
            "by": user_email,
            "message": "Đang khởi tạo...",
            "started_at": firestore.SERVER_TIMESTAMP
        }, merge=True)
        return True, None, None

    tx = db.transaction()
    return _txn(tx)

def release_lock(soc: str, message: str = "Đã hoàn thành"):
    lock_ref(soc).set({
        "is_running": False,
        "message": message,
        "by": None,
        "finished_at": firestore.SERVER_TIMESTAMP
    }, merge=True)


# --- GOOGLE OAUTH SCOPES ---
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid"
]

# --- TRANG CHỦ ---
@app.route("/")
def index():
    if "user_email" in session:
        user_email = session["user_email"]
        doc = db.collection("users").document(user_email).get()
        if doc.exists:
            return render_template("index.html", email=user_email)
        else:
            session.clear()
            return redirect("/login")
    return redirect("/login")

@app.route("/bda")
def page_bda():
    return _render_soc_page("bda")

@app.route("/bdb")
def page_bdb():
    return _render_soc_page("bdb")

def _render_soc_page(soc: str):
    soc = (soc or "").lower()
    if soc not in SOC_CONFIG:
        return "Not found", 404

    if "user_email" not in session:
        return redirect("/login")

    user_email = session["user_email"]
    doc = db.collection("users").document(user_email).get()
    if not doc.exists:
        session.clear()
        return redirect("/login")

    return render_template(
        "mail.html",
        email=user_email,
        soc=soc,
        soc_name=SOC_CONFIG[soc]["name"],
    )

# --- Bắt Đầu Đăng Nhập ---
@app.route("/login")
def login():
    credentials_json = os.environ.get("CREDENTIALS_JSON")
    if not credentials_json:
        return "❌ Thiếu CREDENTIALS_JSON", 500
    credentials_dict = json.loads(credentials_json)

    flow = Flow.from_client_config(
        credentials_dict,
        scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(auth_url)

# --- CALLBACK SAU LOGIN ---
@app.route("/oauth2callback")
def oauth2callback():
    if "state" not in session:
        session.clear()
        return redirect("/login")

    credentials_json = os.environ.get("CREDENTIALS_JSON")
    credentials_dict = json.loads(credentials_json)

    flow = Flow.from_client_config(
        credentials_dict,
        scopes=SCOPES,
        state=session["state"],
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    # Tự động làm mới token nếu hết hạn
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                return f"❌ Không thể refresh token: {e}", 401
        else:
            return "❌ Token không hợp lệ và không có refresh_token", 401

    oauth2_client = build("oauth2", "v2", credentials=creds)
    user_info = oauth2_client.userinfo().get().execute()
    user_email = user_info["email"]

    # Chỉ cho phép domain cụ thể
    if not (user_email.endswith("@shopee.com") or user_email.endswith("@spxexpress.com")):
        return f"❌ Email không được phép truy cập: {user_email}", 403

    db.collection("users").document(user_email).set({
        "token": creds.to_json()
    })
    session["user_email"] = user_email
    return redirect("/")

# --- API CHECK TRẠNG THÁI ---
@app.route("/status")
def check_status():
    soc = request.args.get("soc", "").lower()
    if soc not in SOC_CONFIG:
        return jsonify({"error": "Unknown soc"}), 400
    return jsonify(read_lock(soc))

# --- API CHECK LOG ---
@app.route("/log")
def view_log():
    try:
        with open("app.log", "r", encoding="utf-8") as f:
            log_content = f.read()
    except Exception as e:
        log_content = f"Lỗi khi đọc log: {e}"

    return render_template("log.html", log=log_content)

# --- API CHẠY Gửi MAIL ---
@app.route("/run", methods=["POST"])
def run_batch():
    if "user_email" not in session:
        return jsonify({"status": "error", "message": "Chưa đăng nhập"}), 401

    user_email = session["user_email"]
    user_doc = db.collection("users").document(user_email).get()
    if not user_doc.exists:
        session.clear()
        return jsonify({"status": "error", "message": "Token đã bị xoá. Vui lòng đăng nhập lại."}), 401

    payload = request.get_json(silent=True) or {}
    soc = (payload.get("soc") or "").lower()
    if soc not in SOC_CONFIG:
        return jsonify({"status": "error", "message": f"Unknown soc: {soc}"}), 400

    ok, by, _ = acquire_lock(soc, user_email)
    if not ok:
        return jsonify({"status": "busy", "message": f"Đang có người khác gửi: {by}", "by": by}), 409

    spreadsheet_id = SOC_CONFIG[soc]["sheet_id"]

    def task():
        try:
            lock_ref(soc).set({"message": "Đang gửi email..."}, merge=True)
            run_main(user_email, spreadsheet_id)   # <-- main.py mới
            release_lock(soc, "Đã hoàn thành")
        except Exception as e:
            release_lock(soc, f"Lỗi: {e}")

    threading.Thread(target=task, daemon=True).start()
    return jsonify({"status": "started", "message": "Đã bắt đầu gửi mail"})

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/healthz")
def healthz():
    return "OK", 200

@app.route("/admin")
def admin():
    if "user_email" not in session:
        return redirect("/login")
    if session["user_email"].lower() != ADMIN_EMAIL.lower():
        return "Forbidden", 403

    locks = {soc: read_lock(soc) for soc in SOC_CONFIG.keys()}
    return render_template("admin.html", email=session["user_email"], locks=locks, soc_config=SOC_CONFIG)

@app.route("/force-unlock", methods=["POST"])
def force_unlock():
    if "user_email" not in session:
        return jsonify({"status": "error", "message": "Chưa đăng nhập"}), 401
    if session["user_email"].lower() != ADMIN_EMAIL.lower():
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    soc = (payload.get("soc") or "").lower()
    if soc not in SOC_CONFIG:
        return jsonify({"status": "error", "message": f"Unknown soc: {soc}"}), 400

    release_lock(soc, "Force unlocked by admin")
    return jsonify({"status": "ok", "message": f"Unlocked {soc}"})


if __name__ == "__main__":
    app.run(debug=False)
