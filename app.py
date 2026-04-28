import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from utils.gemini_adapter import translate_field_input, get_embedding
from utils.maps_client import find_nearest_resources
from utils.storage import upload_file
from utils.db import (
    setup_schema, save_submission, get_all_submissions,
    get_gap_stats, resolve_submission,
    find_similar_crises, upsert_embedding,
    create_user, authenticate_user, get_user_by_id,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None
    user_data = get_user_by_id(int(user_id))
    if user_data:
        return User(id=user_data['id'], username=user_data['username'], role=user_data['role'])
    return None

# Setup DB schema on startup
setup_schema()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = authenticate_user(username, password)
        if user_data:
            user = User(id=user_data['id'], username=user_data['username'], role=user_data['role'])
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/stats")
@login_required
def stats():
    return jsonify(get_gap_stats())


@app.route("/api/submit", methods=["POST"])
@login_required
def submit():
    """
    Main pipeline:
    1. Gemini translates hyperlocal Tamil/dialect input
    2. Gemini embedding → semantic search for similar past crises
    3. OpenStreetMap finds nearest NGOs/welfare centres
    4. Save everything to Supabase
    """
    data        = request.get_json() or {}
    raw_input   = data.get("raw_input", "").strip()
    location    = data.get("location", "")
    worker_name = data.get("worker_name", "")

    if not raw_input:
        return jsonify({"error": "raw_input is required"}), 400

    # Step 1 — Gemini dialect translation + crisis classification
    translated = translate_field_input(raw_input)

    # Step 2 — Semantic similarity search (finds how similar past crises were resolved)
    embedding = get_embedding(translated["summary"])
    similar   = find_similar_crises(embedding) if embedding else []

    # Step 3 — OpenStreetMap resource proximity matching
    resources = find_nearest_resources(location, translated.get("crisis_tags", []))

    # Step 4 — Persist to Supabase
    doc_id = save_submission({
        "raw_input":   raw_input,
        "location":    location,
        "worker_name": worker_name,
        "translated":  translated,
        "resources":   resources,
        "similar":     similar,
    })

    return jsonify({
        "doc_id":     doc_id,
        "translated": translated,
        "similar":    similar,
        "resources":  resources,
    })


@app.route("/api/submissions")
@login_required
def submissions():
    return jsonify(get_all_submissions())


@app.route("/api/extract-text", methods=["POST"])
@login_required
def extract_text():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    
    # Check file type
    allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png'}
    if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
        return jsonify({"error": "Unsupported file type"}), 400
    
    try:
        # Upload to Supabase Storage
        file_content = file.read()
        public_url = upload_file(file_content, file.filename, file.content_type)
        
        # In a real production app, you would pass the file_content to Gemini Vision API here
        extracted_text = f"[Extracted from {file.filename}]: Placeholder text. Real vision extraction coming soon."
        
        return jsonify({
            "text": extracted_text,
            "file_url": public_url
        })
    except Exception as e:
        return jsonify({"error": f"Extraction failed: {str(e)}"}), 500


@app.route("/api/resolve/<doc_id>", methods=["POST"])
@login_required
def resolve(doc_id):
    if current_user.role != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    """Mark a submission resolved + embed it for future similarity search."""
    data  = request.get_json() or {}
    notes = data.get("notes", "")

    # Update DB
    resolve_submission(doc_id, notes)

    # Embed resolved crisis so future searches benefit
    all_subs = get_all_submissions(200)
    for s in all_subs:
        if s["id"] == doc_id:
            summary  = s.get("translated", {}).get("summary", "")
            tags     = s.get("translated", {}).get("crisis_tags", [])
            emb      = get_embedding(summary)
            if emb:
                upsert_embedding(doc_id, summary, tags, emb, notes)
            break

    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
