from flask import Flask, jsonify, request, render_template
import main
import os
import threading

app = Flask(__name__)

# Biến toàn cục theo dõi trạng thái
status = {
    "running": False,
    "message": "Chưa chạy"
}

# Trang chính hiển thị giao diện
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

# Hàm chạy nền gọi main.main()
def run_main_background():
    try:
        status["running"] = True
        status["message"] = "Đang chạy..."
        main.main()
        status["message"] = "Đã hoàn thành"
    except Exception as e:
        status["message"] = f"Lỗi: {e}"
    finally:
        status["running"] = False

# API khởi chạy thread nền
@app.route("/run", methods=["POST"])
def run_batch():
    try:
        if status["running"]:
            return jsonify({"status": "running", "message": "Đang chạy, vui lòng đợi hoàn thành."}), 200

        threading.Thread(target=run_main_background).start()
        return jsonify({"status": "started", "message": "Emails đang được gửi ở nền"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# API kiểm tra trạng thái
@app.route("/status", methods=["GET"])
def check_status():
    return jsonify(status)

# Khởi chạy Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)