from flask import Flask, render_template, request, redirect, jsonify, url_for, flash, session, send_from_directory
from sklearn import logger
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import sqlite3, os, requests, docx, uuid, logging, json

app = Flask(__name__)
app.secret_key = os.urandom(24)

DB_FILE = 'AdStorage.db'

OPENROUTER_API_KEY = "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"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json"
}

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                name TEXT NOT NULL, 
                age INTEGER, 
                expectation TEXT, 
                marketing TEXT)
        ''')
        # Create tasks table
        c.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                completed INTEGER DEFAULT 0,
                priority TEXT,
                summary TEXT,
                tag TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS ai_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                filename TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS academy_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            content TEXT,
            image_url TEXT)
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS pricing_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            content TEXT,
            image_url TEXT)
        ''')


        conn.commit()

        c.execute('SELECT COUNT(*) FROM academy_lessons')
        count = c.fetchone()[0]
        if count == 0:
            seed_lessons(conn)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        form = request.form
        email = form['email']
        password = form['password']
        name = form.get('name')
        age = form.get('age')
        expectation = form.get('expectation')
        marketing = form.get('marketing')

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

            if user:
                if check_password_hash(user[2], password):
                    session['user_id'] = user[0]
                    session['name'] = user[3]
                    session['email'] = email
                    return redirect(url_for('dashboard'))
                else:
                    flash("Incorrect password.", "danger")
            else:
                print("DEBUG form values:")
                print("Name:", name)
                print("Age:", age)
                print("Expectation:", expectation)
                print("Marketing:", marketing)

                if all([name, age, expectation, marketing]):
                    hashed_pw = generate_password_hash(password)
                    cursor.execute("""
                        INSERT INTO users (email, password, name, age, expectation, marketing)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (email, hashed_pw, name, age, expectation, marketing))
                    conn.commit()
                    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                    new_id = cursor.fetchone()[0]
                    session['user_id'] = new_id
                    session['name'] = name
                    session['email'] = email
                    return redirect(url_for('dashboard'))
                if not all([name, age, expectation, marketing]):
                    # Show form again, prompting user to fill missing fields
                    flash("Welcome! Please complete your profile to register.", "info")
                    return render_template("auth.html", show_extra_fields=True, email=email)

    return render_template("auth.html")

@app.route('/auth/check_user', methods=['POST'])
def check_user():
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    email = data.get('email')

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        exists = cursor.fetchone() is not None
        return jsonify({'exists': exists})

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))  # Redirect to login page

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get user info
        cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            flash("User not found.", "danger")
            return redirect(url_for('auth'))

        # Get all tasks for this user
        cursor.execute("""
            SELECT id, title, description, summary, tag, priority, completed
            FROM tasks
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))
        task_rows = cursor.fetchall()

    tasks = [{
        'id': row['id'],
        'title': row['title'],
        'description': row['description'],
        'summary': row['summary'],
        'tag': row['tag'],
        'priority': row['priority'],
        'completed': row['completed']
    } for row in task_rows]

    return render_template("dashboard.html", user_name=user["name"], tasks=tasks)


# Helper Functions
def call_openrouter_gpt(prompt, max_tokens=800):
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=15
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

    except requests.exceptions.HTTPError as http_err:
        logger.exception("HTTP error: %s", http_err)
    except requests.exceptions.RequestException as req_err:
        logger.exception("Request error: %s", req_err)
    except json.JSONDecodeError as json_err:
        logger.exception("JSON decode error: %s", json_err)
    except Exception:
        logger.exception("General error in call_openrouter_gpt")

    return "Sorry, something went wrong while trying to respond. Please try again in a moment."

# --- AI Endpoints ---
@app.route("/ai/summarize_task", methods=["POST"])
def ai_summarize_task():
    data = request.get_json()
    desc = data.get("description", "").strip()

    if not desc:
        return jsonify({"summary": "", "error": "No description provided."}), 400

    prompt = (f"Summarize the following task description in one siungle concise sentence:\n\n{desc}\n\n"
              f"Only respond with the summary and one sentence.")
    summary = call_openrouter_gpt(prompt)
    return jsonify({"summary": summary})


@app.route("/ai/suggest_tag", methods=["POST"])
def ai_suggest_tag():
    data = request.get_json()
    title = data.get("title", "").strip()
    desc = data.get("description", "").strip()

    if not title and not desc:
        return jsonify({"tag": "", "error": "No input provided."}), 400

    prompt = (
        f"Given the following task information:\n\n"
        f"Title: {title}\nDescription: {desc}\n\n"
        f"Suggest ONE short, general category tag for this task. "
        f"Do not include punctuation or explanations."
    )

    tag = call_openrouter_gpt(prompt)
    return jsonify({"tag": tag})


# --- Task Operations ---
@app.route('/dashboard/add_task', methods=['POST'])
def add_task():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    title = request.form.get('title')
    description = request.form.get('description')
    priority = request.form.get('priority')
    completed = 0

    if not title:
        flash("Task title is required.", "warning")
        return redirect(url_for('dashboard'))

    try:
        summary = call_openrouter_gpt(f"Summarize: {description}")
        tag = call_openrouter_gpt(f"Title: {title}\nDescription: {description}\nGive one debate-related tag.")
    except Exception as e:
        print("AI Error:", e)
        summary = ""
        tag = ""

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tasks (user_id, title, description, completed, priority, summary, tag)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, title, description, completed, priority, summary, tag))
        conn.commit()

    flash("Task added with AI enhancements!", "success")
    return redirect(url_for('dashboard'))


@app.route('/dashboard/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()

    flash("Task deleted.", "success")
    return redirect(url_for('dashboard'))

@app.route('/message', methods=['POST'])
def chatbot_message():
    data = request.json
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please enter a message so I can respond."})

    prompt = f"""
    You are a professional yet accessible chatbot aimed at helping the user with their advertisement/buisness related issues. 
    A user has written the following message: "{user_message}". 
    Please respond professionally with high quality. 
    Always respond in 1 - 2 paragraphs, not bullet points/lists.
    """

    bot_reply = call_openrouter_gpt(prompt, max_tokens=800)
    return jsonify({"reply": bot_reply})

@app.route('/optimization', methods=['GET', 'POST'])
def optimization():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        media = request.files['media']

        if not media:
            flash("Please upload a file.", "warning")
            return redirect(url_for('optimization'))

        filename = secure_filename(media.filename)
        media_path = os.path.join('static/uploads', filename)
        os.makedirs(os.path.dirname(media_path), exist_ok=True)
        media.save(media_path)

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO ai_projects (user_id, title, description, filename)
                VALUES (?, ?, ?, ?)
            ''', (user_id, title, description, filename))
            conn.commit()

        flash("Project uploaded successfully!", "success")
        return redirect(url_for('optimization'))

    # GET: show all user's projects
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM ai_projects
            WHERE user_id = ?
            ORDER BY timestamp DESC
        ''', (user_id,))
        projects = cursor.fetchall()

    return render_template("optimization.html", projects=projects)

def is_video_file(filename):
    video_extensions = ('.mp4', '.webm', '.ogg')
    return filename.lower().endswith(video_extensions)

# Step 3: File Access
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('static/uploads', filename)

def generate_ai_analysis_for_project(project):
    """
    Calls OpenRouter GPT to generate all analysis fields for analysis.html for the given project.
    Returns a dictionary with all the variables expected by the template.
    """
    media_type = "VIDEO" if is_video_file(project['filename']) else "IMAGE"

    prompt = f"""
        You are an expert marketing AI analysis system.
        
        Analyze this {media_type} ad project:
        
        Title: {project['title']}
        Description: {project['description']}
        Filename: {project['filename']}
        
        Right now, I can tell you that this is a good advertisement.
        
        Give marketing predictions, emotional arc analysis, and coaching in STRICT JSON:
        
        {{
          "ai_caption": "Short direct caption for the ad.",
          "ai_impact_score": integer (0-100),
          "ai_impact_confidence": "High" | "Moderate" | "Low",
          "ai_impact_prediction": "Short paragraph forecasting ad performance.",
          "ai_impact_suggestions": ["Three short improvement suggestions."],
          "sentiment_data": {{
            "labels": ["Time label 1", "Time label 2", ...],
            "scores": [float between -1 and 1 for each label]
          }},
          "dominant_emotion": "One-word emotion label.",
          "peak_time": "Timestamp + description, e.g. 0:36 - Surprising twist",
          "average_sentiment": "e.g. +0.42 (positive)",
          "sentiment_summary": "Short paragraph summarizing emotional arc.",
          "emotional_moments": ["Three key emotional moments."],
          "ai_coaching_insights": "Paragraph of coaching advice.",
          "strengths": ["Three bullet-point strengths."],
          "improvement_tips": ["Three bullet-point improvement tips."],
          "audience_fit": "Short text describing target audience fit.",
          "detected_tones": ["3-5 tone words."],
          "cta_feedback": "Short paragraph of feedback on the CTA."
        }}
        
        IMPORTANT:
        - Clearly consider it's a {media_type} in your analysis.
        - For VIDEO mention pacing, audio cues, motion.
        - For IMAGE mention color, layout, static impact.
        - Only return VALID JSON. No explanations or extra text.
    """

    raw = call_openrouter_gpt(prompt, max_tokens=1200)

    try:
        analysis_data = json.loads(raw)
    except Exception as e:
        logger.exception("AI analysis JSON parsing error: %s", e)
        # Fallback
        analysis_data = {
            "ai_caption": "Auto caption not available.",
            "ai_impact_score": 60,
            "ai_impact_confidence": "Moderate",
            "ai_impact_prediction": "Analyzing impact predictions...",
            "ai_impact_suggestions": [
                "Ensure stronger call-to-action",
                "Consider shortening intro",
                "Use more vibrant colors in thumbnail"
            ],
            "sentiment_data": {
                "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
                "scores": [0.2, 0.5, -0.1, 0.4]
            },
            "dominant_emotion": "Joy",
            "peak_time": "0:36 - Surprising twist",
            "average_sentiment": "+0.42 (positive)",
            "sentiment_summary": (
                "The ad starts with neutral anticipation, quickly builds joy and trust, "
                "and ends with a surprising upbeat conclusion that enhances brand recall."
            ),
            "emotional_moments": [
                "0:12 – Spike in joy due to music",
                "0:36 – Surprise during offer reveal",
                "1:05 – Trust and joy peak at closing message"
            ],
            "ai_coaching_insights": (
                "Generating coaching insights based on language, pacing, and message impact..."
            ),
            "strengths": [
                "Strong emotional hook in opening",
                "Clean, professional visuals",
                "Clear brand messaging"
            ],
            "improvement_tips": [
                "CTA could be more specific",
                "Ending lacks emotional resolution",
                "Voiceover pacing is slightly rushed"
            ],
            "audience_fit": (
                "The ad aligns well with urban Gen-Z consumers, leveraging upbeat tempo, "
                "vibrant visuals, and casual language that resonates with digitally native viewers."
            ),
            "detected_tones": ["Inspiring", "Upbeat", "Sincere", "Motivational"],
            "cta_feedback": (
                "The CTA is positioned clearly at the end but could benefit from a stronger sense "
                "of urgency or a more emotional push to convert."
            )
        }

    return analysis_data

@app.route('/project/<int:project_id>')
def project_analysis(project_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM ai_projects
            WHERE id = ? AND user_id = ?
        """, (project_id, user_id))
        project = cursor.fetchone()

        if not project:
            flash("Project not found.", "danger")
            return redirect(url_for('optimization'))

    # 🔥 AI Generation
    analysis_data = generate_ai_analysis_for_project(project)

    return render_template(
        "analysis.html",
        project=project,
        ai_caption=analysis_data.get("ai_caption"),
        ai_impact_score=analysis_data.get("ai_impact_score"),
        ai_impact_confidence=analysis_data.get("ai_impact_confidence"),
        ai_impact_prediction=analysis_data.get("ai_impact_prediction"),
        ai_impact_suggestions=analysis_data.get("ai_impact_suggestions"),
        sentiment_data=json.dumps(analysis_data.get("sentiment_data")),
        dominant_emotion=analysis_data.get("dominant_emotion"),
        peak_time=analysis_data.get("peak_time"),
        average_sentiment=analysis_data.get("average_sentiment"),
        sentiment_summary=analysis_data.get("sentiment_summary"),
        emotional_moments=analysis_data.get("emotional_moments"),
        ai_coaching_insights=analysis_data.get("ai_coaching_insights"),
        strengths=analysis_data.get("strengths"),
        improvement_tips=analysis_data.get("improvement_tips"),
        audience_fit=analysis_data.get("audience_fit"),
        detected_tones=analysis_data.get("detected_tones"),
        cta_feedback=analysis_data.get("cta_feedback")
    )

@app.route('/academy')
def academy():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        lessons = conn.execute("SELECT * FROM academy_lessons ORDER BY id DESC").fetchall()
    return render_template("academy.html", courses=lessons)

def seed_lessons(conn):
    # 10 hardcoded initial lessons
    lessons = [
        ("Intro to Ad Copywriting",
         "Learn how to write compelling ad copy.",
         "In this lesson, you'll learn the core principles of persuasive ad writing. Includes emotional triggers, value propositions, and call-to-action strategies. [Chart: Emotional Triggers Chart]",
         "https://via.placeholder.com/600x300?text=Emotional+Triggers"),

        ("Audience Segmentation",
         "Master the art of segmenting your audience.",
         "Detailed lesson on demographic, psychographic, and behavioral segmentation. [Chart: Segmentation Funnel]",
         "https://via.placeholder.com/600x300?text=Segmentation+Funnel"),

        ("Social Media Strategy",
         "Develop a winning social media plan.",
         "Learn scheduling, content pillars, and engagement hacks. [Chart: Social Content Calendar Example]",
         "https://via.placeholder.com/600x300?text=Content+Calendar"),

        ("Video Advertising Essentials",
         "Create effective video ads.",
         "Step-by-step on scripting, storyboarding, and distribution. [Chart: Video Funnel Stages]",
         "https://via.placeholder.com/600x300?text=Video+Funnel"),

        ("Email Marketing",
         "Design high-converting email campaigns.",
         "Techniques for subject lines, copy, and automation workflows. [Chart: Email Automation Flow]",
         "https://via.placeholder.com/600x300?text=Email+Flow"),

        ("Landing Page Optimization",
         "Maximize conversion rates.",
         "Best practices for layout, headlines, CTAs, and split testing. [Chart: Conversion Rate Benchmark]",
         "https://via.placeholder.com/600x300?text=Conversion+Benchmark"),

        ("Brand Positioning",
         "Define your unique market position.",
         "Frameworks to identify your brand's voice and value. [Chart: Positioning Map]",
         "https://via.placeholder.com/600x300?text=Positioning+Map"),

        ("Google Ads Mastery",
         "Unlock advanced Google Ads techniques.",
         "Bidding strategies, keywords, and ad extensions. [Chart: Quality Score Factors]",
         "https://via.placeholder.com/600x300?text=Quality+Score"),

        ("Influencer Marketing",
         "Leverage influencers to boost reach.",
         "Selecting, negotiating, and measuring partnerships. [Chart: Influencer ROI]",
         "https://via.placeholder.com/600x300?text=Influencer+ROI"),

        ("Analytics and Reporting",
         "Measure what matters.",
         "KPIs, dashboards, attribution models. [Chart: Attribution Models Comparison]",
         "https://via.placeholder.com/600x300?text=Attribution+Models")
    ]

    for title, desc, content, img in lessons:
        conn.execute(
            "INSERT INTO academy_lessons (title, description, content, image_url) VALUES (?, ?, ?, ?)",
            (title, desc, content, img)
        )
    conn.commit()

@app.route('/academy/ai_add_lesson', methods=['POST'])
def ai_add_lesson():
    data = request.get_json()
    topic = data.get('topic', '').strip()

    if not topic:
        return jsonify({'error': 'No topic provided'}), 400

    title_prompt = f"Generate a concise lesson title on the topic: {topic}"
    desc_prompt = f"Write a 7 word description on this: {topic}."
    content_prompt = (f"Write a detailed, structured lesson on {topic}, including best practices, examples, and "
                      f"suggest a chart. Keep all of this as paragraphs without headings or stylized font "
                      f"(bold, italics, underline, etc.)")

    title = call_openrouter_gpt(title_prompt)
    description = call_openrouter_gpt(desc_prompt)
    content = call_openrouter_gpt(content_prompt)

    image_url = f"https://via.placeholder.com/600x300?text={topic.replace(' ', '+')}"

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO academy_lessons (title, description, content, image_url) VALUES (?, ?, ?, ?)",
            (title, description, content, image_url)
        )
        conn.commit()

    return jsonify({'message': 'Lesson generated successfully!'})

@app.route('/academy/delete_lesson/<int:lesson_id>', methods=['POST'])
def delete_lesson(lesson_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM academy_lessons WHERE id = ?", (lesson_id,))
        conn.commit()
    return jsonify({'message': 'Lesson deleted successfully'})

@app.route('/academy/course/<int:lesson_id>')
def course_detail(lesson_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        lesson = conn.execute(
            "SELECT * FROM academy_lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
        if not lesson:
            return "<p>Lesson not found.</p>", 404

    return render_template("lesson_partial.html", lesson=lesson)

@app.route('/financial')
def financial_dashboard():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        analyses = conn.execute("SELECT * FROM pricing_analyses ORDER BY id DESC").fetchall()
    return render_template("financial.html", analyses=analyses)


@app.route('/financial/ai_add_analysis', methods=['POST'])
def ai_add_analysis():
    data = request.get_json()
    topic = data.get('topic', '').strip()

    if not topic:
        return jsonify({'error': 'No topic provided'}), 400

    title_prompt = f"Generate a clear, professional analysis title for the topic: {topic}."
    desc_prompt = f"Write a 1-2 sentence description for a financial analysis on {topic}."
    content_prompt = f"Write a detailed, structured financial analysis about {topic}, including sections on ROI, pricing strategy, competitive landscape, and suggested charts or graphs. Include headings and subheadings."

    title = call_openrouter_gpt(title_prompt)
    description = call_openrouter_gpt(desc_prompt)
    content = call_openrouter_gpt(content_prompt)
    image_url = f"https://via.placeholder.com/600x300?text={topic.replace(' ', '+')}"

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO pricing_analyses (title, description, content, image_url) VALUES (?, ?, ?, ?)",
            (title, description, content, image_url)
        )
        conn.commit()

    return jsonify({'message': 'Analysis generated successfully!'})


@app.route('/financial/analysis/<int:analysis_id>')
def analysis_detail(analysis_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        analysis = conn.execute(
            "SELECT * FROM pricing_analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        if not analysis:
            return "<p>Analysis not found.</p>", 404

    return render_template("analysis_partial.html", analysis=analysis)


@app.route('/financial/delete_analysis/<int:analysis_id>', methods=['POST'])
def delete_analysis(analysis_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM pricing_analyses WHERE id = ?", (analysis_id,))
        conn.commit()
    return jsonify({'message': 'Analysis deleted successfully.'})

@app.route('/financial')
def financial():
    return render_template("financial.html")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)