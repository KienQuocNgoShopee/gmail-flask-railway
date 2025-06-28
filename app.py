# --- app.py (hoàn chỉnh với Giai Đoạn 3) ---

from flask import Flask, session, redirect, url_for, request, render_template, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
import firebase_admin
from firebase_admin import credentials, firestore
import json
import threading
from main import main as run_main

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --- KHỞdi TẠO FIREBASE ---
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
    "openid"
]


# --- TRạNG THÁI ---
status = {"running": False, "message": "Chưa chạy"}

# --- TRANG CHỦ ---
@app.route("/")
def index():
    if "user_email" in session:
        return render_template("index.html", email=session["user_email"])
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

    oauth2_client = build("oauth2", "v2", credentials=creds)
    user_info = oauth2_client.userinfo().get().execute()
    user_email = user_info["email"]

    db.collection("users").document(user_email).set({
        "token": creds.to_json()
    })
    session["user_email"] = user_email
    return redirect("/")

# --- API CHECK TRẠNG THÁI ---
@app.route("/status")
def check_status():
    return jsonify(status)

# --- API CHẠY Gửi MAIL ---
@app.route("/run", methods=["POST"])
def run_batch():
    if "user_email" not in session:
        return jsonify({"status": "error", "message": "Chưa login"}), 401

    if status["running"]:
        return jsonify({"status": "running", "message": "Đang chạy..."})

    def task():
        try:
            status["running"] = True
            status["message"] = "Đang gửi email..."
            run_main(session["user_email"])
            status["message"] = "Đã hoàn thành"
        except Exception as e:
            status["message"] = f"Lỗi: {e}"
        finally:
            status["running"] = False

    threading.Thread(target=task).start()
    return jsonify({"status": "started", "message": "Đã bắt đầu gửi mail"})

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=False)
