from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import json
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='static')

# Create directories
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), 'projects')
os.makedirs(PROJECTS_DIR, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """Get all saved projects"""
    projects = []
    for filename in os.listdir(PROJECTS_DIR):
        if filename.endswith('.html') or filename.endswith('.py'):
            filepath = os.path.join(PROJECTS_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            projects.append({
                'name': filename,
                'content': content,
                'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
            })
    return jsonify(projects)

@app.route('/api/project', methods=['POST'])
def save_project():
    """Save a project"""
    data = request.json
    filename = data.get('filename')
    content = data.get('content')
    
    if not filename or not content:
        return jsonify({'error': 'Missing filename or content'}), 400
    
    filepath = os.path.join(PROJECTS_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filepath = os.path.join(PROJECTS_DIR, file.filename)
    file.save(filepath)
    
    return jsonify({'success': True, 'filename': file.filename})

@app.route('/api/goose', methods=['POST'])
def goose_integration():
    """Goose AI integration endpoint"""
    data = request.json
    # TODO: Implement Goose AI integration
    return jsonify({'result': 'Goose integration placeholder'})

@app.route('/api/generate-3d', methods=['POST'])
def generate_3d():
    """3D generation endpoint"""
    data = request.json
    # TODO: Implement 3D generation
    return jsonify({'result': '3D generation placeholder'})

@app.route('/api/generate-video', methods=['POST'])
def generate_video():
    """Video generation endpoint"""
    data = request.json
    # TODO: Implement video generation
    return jsonify({'result': 'Video generation placeholder'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
и 
