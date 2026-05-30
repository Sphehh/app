import os, json, time, requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

PIAPI_KEY = os.environ.get('PIAPI_KEY')   # never exposed to frontend
BASE_URL = 'https://api.piapi.ai/api/v1'

# ---------- Prompt loading ----



# Correct path resolution
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

def load_prompts():
    prompts = []
    if not os.path.exists(PROMPTS_DIR):
        os.makedirs(PROMPTS_DIR)  # create if missing (optional)
    for filename in os.listdir(PROMPTS_DIR):
        if filename.endswith('.json'):
            with open(os.path.join(PROMPTS_DIR, filename)) as f:
                prompt = json.load(f)
                prompts.append(prompt)
    return prompts

# ... rest of your routes unchanged ...






# ---------- Frontend routes ----------
@app.route('/')
def index():
    prompts = load_prompts()
    return render_template('index.html', prompts=prompts)

"""@app.route('/editor/<prompt_id>')
def editor(prompt_id):
    # Load the specific prompt and pass it to the editor
    try:
        with open(f'prompts/{prompt_id}.json') as f:
            prompt = json.load(f)
    except FileNotFoundError:
        return "Prompt not found", 404
    return render_template('editor.html', prompt=prompt)"""



@app.route('/editor/<prompt_id>')
def editor(prompt_id):
    filepath = os.path.join(PROMPTS_DIR, f'{prompt_id}.json')
    try:
        with open(filepath) as f:
            prompt = json.load(f)
    except FileNotFoundError:
        return "Prompt not found", 404
    return render_template('editor.html', prompt=prompt)


# ---------- API proxy routes (hide PIAPI_KEY) ----------
@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    prompt_text = data.get('prompt')
    ratio = data.get('ratio', '2:3')
    resolution = data.get('resolution', '2K')

    if not prompt_text:
        return jsonify({'error': 'Prompt is required'}), 400

    payload = {
        'model': 'gemini',
        'task_type': 'nano-banana-2',
        'input': {
            'prompt': prompt_text,
            'output_format': 'png',
            'aspect_ratio': ratio,
            'resolution': resolution
        }
    }

    headers = {'x-api-key': PIAPI_KEY, 'Content-Type': 'application/json'}
    resp = requests.post(f'{BASE_URL}/task', json=payload, headers=headers)
    if resp.status_code != 200:
        return jsonify({'error': f'PiAPI error: {resp.text}'}), 500
    pi_data = resp.json()
    if pi_data.get('code') != 200:
        return jsonify({'error': pi_data.get('message', 'Task creation failed')}), 500

    task_id = pi_data['data']['task_id']

    # Poll for result (max 3 minutes)
    for _ in range(45):
        time.sleep(4)
        poll_resp = requests.get(f'{BASE_URL}/task/{task_id}', headers={'x-api-key': PIAPI_KEY})
        poll_data = poll_resp.json()
        status = poll_data.get('data', {}).get('status') or poll_data.get('status')
        if status == 'completed':
            image_url = poll_data['data']['output']['image_url']
            return jsonify({'image': image_url})
        elif status == 'failed':
            return jsonify({'error': 'Generation failed'}), 500
    return jsonify({'error': 'Timed out'}), 500

@app.route('/api/remove-bg', methods=['POST'])
def api_remove_bg():
    data = request.json
    image_data = data.get('image')   # base64 data URL

    payload = {
        'model': 'Qubico/image-toolkit',
        'task_type': 'background-remove',
        'input': {
            'rmbg_model': 'RMBG-2.0',
            'image': image_data
        }
    }

    headers = {'x-api-key': PIAPI_KEY, 'Content-Type': 'application/json'}
    resp = requests.post(f'{BASE_URL}/task', json=payload, headers=headers)
    if resp.status_code != 200:
        return jsonify({'error': f'BG removal error: {resp.text}'}), 500
    pi_data = resp.json()
    if pi_data.get('code') != 200:
        return jsonify({'error': pi_data.get('message', 'BG removal failed')}), 500

    task_id = pi_data['data']['task_id']

    for _ in range(45):
        time.sleep(4)
        poll_resp = requests.get(f'{BASE_URL}/task/{task_id}', headers={'x-api-key': PIAPI_KEY})
        poll_data = poll_resp.json()
        status = poll_data.get('data', {}).get('status') or poll_data.get('status')
        if status == 'completed':
            image_url = poll_data['data']['output']['image_url']
            return jsonify({'image': image_url})
        elif status == 'failed':
            return jsonify({'error': 'Background removal failed'}), 500
    return jsonify({'error': 'Timed out'}), 500

# ---------- Run ----------
if __name__ == '__main__':
    app.run(debug=True, port=5000)
