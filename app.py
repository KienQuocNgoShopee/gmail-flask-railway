from flask import Flask, jsonify, request, render_template_string
import main
import os
import threading

app = Flask(__name__)

# HTML đơn giản với nút bấm
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Gửi Email</title>
</head>
<body>
    <h2>Gửi Email từ Google Sheets</h2>
    <button onclick="sendEmails()">Chạy gửi mail</button>
    <p id="result"></p>

    <script>
        function sendEmails() {
            fetch('/run', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    document.getElementById('result').innerText = data.message;
                })
                .catch(error => {
                    document.getElementById('result').innerText = 'Lỗi: ' + error;
                });
        }
    </script>
</body>
</html>
"""

# Trang web gốc hiển thị nút
@app.route("/", methods=["GET"])
def home():
    return render_template_string(HTML_PAGE)

# API chạy background task
def run_main_background():
    try:
        main.main()
    except Exception as e:
        print(f"Error in background task: {e}")

@app.route("/run", methods=["POST"])
def run_batch():
    try:
        threading.Thread(target=run_main_background).start()
        return jsonify({"status": "started", "message": "Emails đang được gửi ở nền"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
