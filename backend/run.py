from app import create_app

app = create_app()

if __name__ == "__main__":
    if app.config["APP_CONFIG"] == "production":
        raise SystemExit(
            "Do not use Flask's development server in production; serve wsgi:app with Waitress."
        )
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", False))
