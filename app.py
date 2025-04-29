import gevent  # Import gevent
from gevent import monkey

# Patch the standard library with gevent before importing other modules
monkey.patch_all()

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os
import pickle
import time
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# Define the scope and credentials file
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CREDENTIALS_FILE = r'D:\exports\credentials.json'
TOKEN_FILE = 'token.pickle'

# Initialize Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app, resources={r"/download": {"origins": "http://127.0.0.1:5000"}})
socketio = SocketIO(app, cors_allowed_origins="http://127.0.0.1:5000", async_mode='gevent')  # Use gevent async mode

def authenticate_google_drive():
    """Authenticate with Google Drive API."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    return creds

def normalize_file_name(file_name):
    """Normalize file name by removing '(number)' suffixes."""
    return re.sub(r" \(\d+\)$", "", file_name)

def download_pdf_files_from_folder(folder_id, download_folder, service, processed_file_ids, processed_normalized_names, total_files, current_file):
    print(f"🔍 Scanning folder ID: {folder_id}")
    socketio.emit('progress', {'message': f"Scanning folder ID: {folder_id}"}, namespace='/download')
    print("Emitted: Scanning folder ID")
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents",
            pageSize=1000, fields="nextPageToken, files(id, name, mimeType)"
        ).execute()
        items = results.get('files', [])
        socketio.emit('progress', {'message': f"Found {len(items)} files in folder"}, namespace='/download')
        print(f"Emitted: Found {len(items)} files in folder")
        total_files[0] += len(items)
    except Exception as e:
        socketio.emit('progress', {'message': f"Error listing files in folder {folder_id}: {str(e)}"}, namespace='/download')
        print(f"Emitted: Error listing files - {str(e)}")
        return

    if not items:
        socketio.emit('progress', {'message': "No files found in folder"}, namespace='/download')
        print("Emitted: No files found in folder")
        return

    for item in items:
        file_id = item['id']
        original_name = item['name']
        current_file[0] += 1
        socketio.emit('progress', {
            'message': f"Processing file {current_file[0]} of {total_files[0]}: {original_name}",
            'progress': (current_file[0] / total_files[0]) * 100 if total_files[0] > 0 else 0
        }, namespace='/download')
        print(f"Emitted: Processing file {current_file[0]} of {total_files[0]}: {original_name}")

        if file_id in processed_file_ids:
            socketio.emit('progress', {'message': f"Skipping already processed file ID: {file_id} (Name: {original_name})"}, namespace='/download')
            print(f"Emitted: Skipping already processed file ID: {file_id}")
            continue

        if not original_name.lower().endswith('.pdf'):
            final_file_name = original_name + '.pdf'
        else:
            final_file_name = original_name

        normalized_name = normalize_file_name(final_file_name)
        if normalized_name in processed_normalized_names:
            socketio.emit('progress', {'message': f"Skipping duplicate (normalized): {final_file_name} (normalized to {normalized_name})"}, namespace='/download')
            print(f"Emitted: Skipping duplicate (normalized): {final_file_name}")
            continue

        file_path = os.path.join(download_folder, final_file_name)
        base_name, extension = os.path.splitext(final_file_name)
        counter = 1
        while os.path.exists(file_path):
            new_file_name = f"{base_name}_{counter}{extension}"
            file_path = os.path.join(download_folder, new_file_name)
            counter += 1

        for attempt in range(3):
            try:
                if item['mimeType'] == 'application/pdf':
                    socketio.emit('progress', {'message': f"Found PDF: {final_file_name}"}, namespace='/download')
                    print(f"Emitted: Found PDF: {final_file_name}")
                    request = service.files().get_media(fileId=file_id)
                elif item['mimeType'] == 'application/vnd.google-apps.document':
                    socketio.emit('progress', {'message': f"Found Google Doc, exporting as PDF: {final_file_name}"}, namespace='/download')
                    print(f"Emitted: Found Google Doc, exporting as PDF: {final_file_name}")
                    request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
                else:
                    socketio.emit('progress', {'message': f"Skipping non-PDF/Google Doc file: {original_name}"}, namespace='/download')
                    print(f"Emitted: Skipping non-PDF/Google Doc file: {original_name}")
                    break

                with open(file_path, 'wb') as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        try:
                            status, done = downloader.next_chunk()
                            if status:
                                socketio.emit('progress', {
                                    'message': f"Downloading {final_file_name}: {int(status.progress() * 100)}%",
                                    'progress': (current_file[0] - 1 + status.progress()) / total_files[0] * 100 if total_files[0] > 0 else 0
                                }, namespace='/download')
                                print(f"Emitted: Downloading {final_file_name}: {int(status.progress() * 100)}%")
                        except Exception as e:
                            socketio.emit('progress', {'message': f"Error downloading {final_file_name}: {str(e)}"}, namespace='/download')
                            print(f"Emitted: Error downloading {final_file_name}: {str(e)}")
                            if os.path.exists(file_path):
                                os.remove(file_path)
                            raise

                    file_size = os.path.getsize(file_path)
                    if file_size == 0:
                        socketio.emit('progress', {'message': f"Downloaded file {final_file_name} is 0 KB, deleting..."}, namespace='/download')
                        print(f"Emitted: Downloaded file {final_file_name} is 0 KB, deleting...")
                        os.remove(file_path)
                        raise Exception("File is 0 KB")
                    else:
                        socketio.emit('progress', {
                            'message': f"Downloaded {final_file_name} to {file_path} (Size: {file_size / 1024:.2f} KB)",
                            'progress': (current_file[0] / total_files[0]) * 100 if total_files[0] > 0 else 0
                        }, namespace='/download')
                        print(f"Emitted: Downloaded {final_file_name} to {file_path} (Size: {file_size / 1024:.2f} KB)")
                        processed_file_ids.add(file_id)
                        processed_normalized_names.add(normalized_name)
                        break

            except Exception as e:
                socketio.emit('progress', {'message': f"Attempt {attempt + 1} failed for {final_file_name}: {str(e)}"}, namespace='/download')
                print(f"Emitted: Attempt {attempt + 1} failed for {final_file_name}: {str(e)}")
                if attempt == 2:
                    socketio.emit('progress', {'message': f"Giving up on {final_file_name} after 3 attempts"}, namespace='/download')
                    print(f"Emitted: Giving up on {final_file_name} after 3 attempts")
                    break
                time.sleep(2)

def process_folder(folder_id, download_folder, service, processed_file_ids=None, processed_normalized_names=None, total_files=None, current_file=None):
    if processed_file_ids is None:
        processed_file_ids = set()
    if processed_normalized_names is None:
        processed_normalized_names = set()
    if total_files is None:
        total_files = [0]
    if current_file is None:
        current_file = [0]

    download_pdf_files_from_folder(folder_id, download_folder, service, processed_file_ids, processed_normalized_names, total_files, current_file)

    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder'",
            pageSize=1000, fields="nextPageToken, files(id, name)"
        ).execute()
        subfolders = results.get('files', [])
    except Exception as e:
        socketio.emit('progress', {'message': f"Error listing subfolders in folder {folder_id}: {str(e)}"}, namespace='/download')
        print(f"Emitted: Error listing subfolders - {str(e)}")
        return

    for subfolder in subfolders:
        socketio.emit('progress', {'message': f"Entering subfolder: {subfolder['name']}"}, namespace='/download')
        print(f"Emitted: Entering subfolder: {subfolder['name']}")
        process_folder(subfolder['id'], download_folder, service, processed_file_ids, processed_normalized_names, total_files, current_file)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download_pdfs():
    try:
        data = request.get_json()
        folder_id = data.get('folder_id')
        download_folder = data.get('download_folder')

        if not folder_id or not download_folder:
            return jsonify({"error": "Please enter both a folder ID and download folder"}), 400

        os.makedirs(download_folder, exist_ok=True)
        creds = authenticate_google_drive()
        service = build('drive', 'v3', credentials=creds)
        process_folder(folder_id, download_folder, service)
        socketio.emit('progress', {'message': "Download completed successfully!", 'progress': 100}, namespace='/download')
        print("Emitted: Download completed successfully!")
        return jsonify({"message": "Download initiated"})
    except Exception as e:
        socketio.emit('progress', {'message': f"Backend error: {str(e)}", 'progress': 0}, namespace='/download')
        print(f"Emitted: Backend error - {str(e)}")
        return jsonify({"error": f"Backend error: {str(e)}"}), 500

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, use_reloader=False)  # Disable reloader to avoid issues with gevent