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

# --- TRẠNG THÁI ---
status = {
    "running": False,
    "message": "Chưa chạy",
    "by": None
}

# --- TRANG CHỦ ---
@app.route("/")
def index():
    if "user_email" in session:
        user_email = session["user_email"]
        doc = db.collection("users").document(user_email).get()
        if doc.exists:
            return render_template("index.html", email=user_email)
        else:
            session.pop("user_email", None) 
            return redirect("/login")
    return redirect("/login")


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
    return jsonify({
        "running": status["running"],
        "message": status["message"],
        "by": status["by"]
    })

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

    if status["running"] and status.get("by") != user_email:
        return jsonify({
            "status": "busy",
            "message": f"Đang có người khác gửi: {status['by']}"
        })

    def task():
        original_stdout = sys.stdout

        try:
            status["running"] = True
            status["by"] = user_email
            status["message"] = "Đang gửi email..."

            sys.stdout = open("app.log", "a", encoding="utf-8") 
            run_main(user_email)
            sys.stdout.close()

            status["message"] = "Đã hoàn thành"

        except Exception as e:
            sys.stdout.close()
            if "invalid_grant" in str(e) or "unauthorized" in str(e).lower():
                status["message"] = "⚠️ Token không hợp lệ. Vui lòng đăng nhập lại."
            else:
                status["message"] = f"Lỗi: {e}"
        finally:
            sys.stdout = original_stdout
            status["running"] = False
            status["by"] = None


    threading.Thread(target=task).start()
    return jsonify({"status": "started", "message": "Đã bắt đầu gửi mail"})

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/healthz")
def healthz():
    return "OK", 200

if __name__ == "__main__":
    app.run(debug=False)
