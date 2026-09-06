from flask import Flask, jsonify, render_template, request

from dashboard import service

app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_ois_curve=service.default_ois_curve(),
        default_cds_curve=service.default_cds_curve(),
        default_params=service.default_contract_params(),
    )


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    try:
        results = service.parse_uploaded_file(request.files["file"])
    except service.CsvParseError as e:
        return jsonify({"error": str(e)}), 400
    except (ValueError, KeyError) as e:
        return jsonify({"error": f"Could not parse file: {e}"}), 400
    return jsonify({"results": results})


@app.route("/api/price", methods=["POST"])
def price():
    payload = request.get_json(force=True)
    try:
        result = service.price(payload)
    except (KeyError, ValueError, IndexError) as e:
        return jsonify({"error": f"Pricing failed: {e}"}), 400
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
