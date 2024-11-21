import argparse
import logging
import datetime
import os
import paramiko
import requests
import json
import socket
from pathlib import Path

# Configure logging to both file and console
today = datetime.date.today().strftime('%Y-%m-%d')

hostname = socket.gethostname()  # Get the current machine's hostname
log_file_name = f"log_collector_{hostname}_{today}.log"

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_file_name)
file_handler.setLevel(logging.DEBUG)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# Load configuration from config.json
def load_config():
    try:
        with open('config.json', 'r') as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        logger.error("Configuration file not found.")
        return None
    except json.JSONDecodeError:
        logger.error("Error parsing configuration file.")
        return None

config = load_config()
if not config:
    exit(1)

# API and remote configuration
token = config.get("api_key")
FILE_API_URL = config.get("file_api_url")
REMOTE_HOST = config.get("remote_host")
REMOTE_USERNAME = config.get("remote_username")
REMOTE_PASSWORD = config.get("remote_password")
REMOTE_FILE_PATH = config.get("remote_file_path")
REMOTE_HOSTNAME= config.get("remote_hostname")
LOCAL_FILE_PATH = config.get("local_file_path")
KNOWLEDGE_ID = config.get("knowledge_id")

# Check if remote fetching is enabled
remote = config.get("remote", False)

# Generate the temp file path with the hostname and today's date
if remote:
    TEMP_LOCAL_FILE_PATH = f"/tmp/{REMOTE_HOSTNAME}_collector_{today}.log"
    UPLOADED_JSON_PATH = "uploaded.json"
else:
    TEMP_LOCAL_FILE_PATH = f"/tmp/{hostname}_collector_{today}.log"
    UPLOADED_JSON_PATH = "uploaded.json"

def save_uploaded_file(file_data):
    """Save the details of the uploaded file to the uploaded.json file."""
    if Path(UPLOADED_JSON_PATH).exists():
        with open(UPLOADED_JSON_PATH, "r") as file:
            uploaded_files = json.load(file)
    else:
        uploaded_files = {}

    uploaded_files[file_data["filename"]] = {
        "file_id": file_data["file_id"],
        "date": file_data["date"]
    }

    with open(UPLOADED_JSON_PATH, "w") as file:
        json.dump(uploaded_files, file, indent=4)
    logger.info(f"Saved uploaded file details: {file_data['filename']}")

def load_uploaded_file():
    """Load the details of uploaded files from the uploaded.json file."""
    if Path(UPLOADED_JSON_PATH).exists():
        with open(UPLOADED_JSON_PATH, "r") as file:
            return json.load(file)
    return {}

def get_remote_file(remote_host, username, password, remote_path, local_path):
    """Download file via SSH."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(remote_host, username=username, password=password)
        sftp = ssh.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        ssh.close()
        logger.info("File downloaded from remote server: %s", remote_host)
        return True
    except Exception as e:
        logger.error("Failed to download file: %s", e)
        return False

def get_local_file(local_path, temp_path):
    """Copy a local file to the temporary location."""
    try:
        if os.path.exists(local_path):
            os.system(f"cp {local_path} {temp_path}")
            logger.info("File copied locally from: %s", local_path)
            return True
        else:
            logger.error("Local file not found at: %s", local_path)
            return False
    except Exception as e:
        logger.error("Error copying local file: %s", e)
        return False

def upload_file_to_vector_database(file_path):
    """Upload file to vector database and log filename with file ID."""
    url = FILE_API_URL
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    try:
        with open(file_path, 'rb') as file:
            filename = os.path.basename(file_path)
            files = {'file': (filename, file)}
            response = requests.post(url, headers=headers, files=files)
            response.raise_for_status()
            file_info = response.json()
            file_id = file_info.get("id")
            if file_id:
                logger.info("File uploaded successfully: Filename: %s, File ID: %s", filename, file_id)
            else:
                logger.warning("File uploaded but no ID returned: Filename: %s", filename)
            return file_id
    except requests.exceptions.RequestException as e:
        logger.error("File upload failed: %s", e)
        return None

def add_file_to_knowledge(file_id, knowledge_id):
    """Add file to a knowledge collection."""
    url = f"https://helpdesk.unixfor.gr/api/v1/knowledge/{knowledge_id}/file/add"
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    data = {"file_id": file_id}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info("File added to knowledge collection.")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Failed to add file to knowledge: %s", e)
        return None

def update_file_in_knowledge(file_id, knowledge_id):
    """Update file in knowledge collection."""
    url = f"https://helpdesk.unixfor.gr/api/v1/knowledge/{knowledge_id}/file/update"
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    data = {"file_id": file_id}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info("File updated in knowledge collection.")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Failed to update file in knowledge: %s", e)
        return None

def remove_file_from_knowledge(file_id, knowledge_id):
    """Remove file from knowledge collection and log file ID."""
    url = f"https://helpdesk.unixfor.gr/api/v1/knowledge/{knowledge_id}/file/remove"
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    data = {"file_id": file_id}
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        if response.status_code == 200:
            logger.info("File removed from knowledge collection: File ID: %s", file_id)
            return response.json()
        else:
            logger.error("Failed to remove file from knowledge collection: File ID: %s, Response: %s", file_id, response.text)
            return None
    except requests.exceptions.RequestException as e:
        logger.error("Error removing file from knowledge collection: File ID: %s, Error: %s", file_id, e)
        return None

def main(args):
    # Load previously uploaded files from the JSON
    uploaded_files = load_uploaded_file()

    # Step 1: Fetch the file
    if remote:
        logger.info("Fetching file from remote server...")
        success = get_remote_file(REMOTE_HOST, REMOTE_USERNAME, REMOTE_PASSWORD, REMOTE_FILE_PATH, TEMP_LOCAL_FILE_PATH)
    else:
        logger.info("Fetching file from local system...")
        success = get_local_file(LOCAL_FILE_PATH, TEMP_LOCAL_FILE_PATH)

    if not success:
        logger.error("File operation failed.")
        return

    # Step 2: Check if file has been uploaded already today
    filename = os.path.basename(TEMP_LOCAL_FILE_PATH)
    if filename in uploaded_files and uploaded_files[filename]["date"] == today:
        logger.info("File already uploaded today.")
        logger.info("Deleting file from collection before re-uploading.")
        file_id = uploaded_files[filename]["file_id"]
        remove_file_from_knowledge(file_id, KNOWLEDGE_ID)
        
        # Re-upload the file and update the knowledge
        logger.info("Re-uploading the file to the knowledge collection.")
        file_id = upload_file_to_vector_database(TEMP_LOCAL_FILE_PATH)
        if not file_id:
            logger.error("File upload failed.")
            return
        
        # Add it to knowledge collection again
        add_file_to_knowledge(file_id, KNOWLEDGE_ID)
        save_uploaded_file({
            "filename": filename,
            "file_id": file_id,
            "date": today
        })

        logger.info("File successfully re-uploaded and added back to knowledge collection.")
    else:
        # Step 3: Upload the file for the first time
        file_id = upload_file_to_vector_database(TEMP_LOCAL_FILE_PATH)
        if not file_id:
            logger.error("File upload failed.")
            return

        # Step 4: Add the file to knowledge and save details to JSON
        add_file_to_knowledge(file_id, KNOWLEDGE_ID)
        save_uploaded_file({
            "filename": filename,
            "file_id": file_id,
            "date": today
        })

        logger.info("File successfully uploaded and added to knowledge collection.")

    # Step 5: Cleanup
    if os.path.exists(TEMP_LOCAL_FILE_PATH):
        os.remove(TEMP_LOCAL_FILE_PATH)
        logger.info("Temporary file cleaned up.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log Collector Utility")
    parser.add_argument("--h", action="store_true", help="Show help")
    parser.add_argument("--add-to-collection", action="store_true", help="Add a file")
    parser.add_argument("--delete-from-collection", type=str, help="Delete a file from a collection by file ID")
    args = parser.parse_args()

    # Check if no arguments are passed
    if len(vars(args)) == 0 or args.h:
        parser.print_help()
    else:
        main(args)
