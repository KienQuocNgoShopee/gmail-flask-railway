from flask import Flask, session, redirect, url_for, request, render_template, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import os
import firebase_admin
from firebase_admin import credentials, firestore
import json
import pathlib

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --- KHỞI TẠO FIREBASE ---
firebase_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
if not firebase_json:
    raise Exception("⚠️ FIREBASE_SERVICE_ACCOUNT_JSON không được thiết lập!")

cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

# --- GOOGLE OAUTH SCOPES ---
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]

# --- TRANG CHỦ ---
@app.route("/")
def index():
    if "user_email" in session:
        return render_template("index.html", email=session["user_email"])
    return redirect("/login")

# --- BẮT ĐẦU ĐĂNG NHẬP ---
@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/oauth2callback"
    )
    #redirect_uri=url_for("oauth2callback", _external=True)
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(auth_url)

# --- XỬ LÝ SAU KHI NGƯỜI DÙNG ĐĂNG NHẬP ---
@app.route("/oauth2callback")
def oauth2callback():
    if "state" not in session:
        return redirect("/login")
    state = session["state"]
    flow = Flow.from_client_secrets_file(
        "credentials.json",
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)

    creds = flow.credentials

    # Lấy email người dùng từ API Google
    oauth2_client = build("oauth2", "v2", credentials=creds)
    user_info = oauth2_client.userinfo().get().execute()
    user_email = user_info["email"]

    # Lưu token vào Firestore
    db.collection("users").document(user_email).set({
        "token": creds.to_json()
    })

    # Ghi nhớ session người dùng
    session["user_email"] = user_email

    return redirect("/")

# --- ĐĂNG XUẤT ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
