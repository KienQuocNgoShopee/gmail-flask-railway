from flask import Flask, jsonify
import main

app = Flask(__name__)

@app.route("/run", methods=["GET"])
def run_batch():
    try:
        main.main()
        return jsonify({"status": "success", "message": "Emails processed"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
