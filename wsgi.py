import os
from app.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 3000)))
    print(f"HireNet running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
