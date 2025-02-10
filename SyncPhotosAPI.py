import os
import json
import requests
import logging
import traceback
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from config import *

# Configure the logger
logging.basicConfig(
    filename='google_photos_sync.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Function to create the local folders if they don't exist
def create_local_folders():
    try:
        os.makedirs(LOCAL_PHOTOS_FOLDER_PATH, exist_ok=True)
        os.makedirs(ARCHIVE_FOLDER_PATH, exist_ok=True)
        os.makedirs(ERROR_FOLDER_PATH, exist_ok=True)
    except IOError as e:
        logger.error(f"Error creating folders: {e}")

# Function to get the access token
def get_access_token(credentials_path, scopes):
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)

    # Save the credentials for future use
    with open('token.json', 'w') as token:
        token.write(creds.to_json())

    return creds.token

# Function to get album details by title (checks both private and shared albums)
def get_album_by_title(access_token, ALBUM_NAME):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        albums = response.json().get("albums", [])
        for album in albums:
            if album["title"] == ALBUM_NAME:
                logger.info(f"Album '{ALBUM_NAME}' already exists with ID: {album['id']}")
                return album

    # Check shared albums
    url = "https://photoslibrary.googleapis.com/v1/sharedAlbums"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        shared_albums = response.json().get("sharedAlbums", [])
        for album in shared_albums:
            if album["title"] == ALBUM_NAME:
                logger.info(f"Found shared album '{ALBUM_NAME}' with ID: {album['id']}")
                return album

    logger.info(f"Album '{ALBUM_NAME}' not found in personal or shared albums.")
    return None
# Function to create a new album (only for private albums)
def create_album(access_token, album_name):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}", "Content-type": "application/json"}
    payload = {"album": {"title": album_name}}

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        album_id = response.json()["id"]
        logger.info(f"Album '{album_name}' created with ID: {album_id}")
        return album_id
    else:
        logger.error(f"Failed to create album '{album_name}'. Response: {response.text}")
        return None

def join_shared_album(access_token, album_id):
    """ Attempt to join a shared album before uploading. """
    url = f"https://photoslibrary.googleapis.com/v1/sharedAlbums/{album_id}:join"
    headers = {"Authorization": f"Bearer {access_token}", "Content-type": "application/json"}
    
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        logger.info(f"Successfully joined shared album with ID: {album_id}")
        return True
    else:
        logger.error(f"Failed to join shared album '{album_id}'. Response: {response.json()}")
        return False
def upload_photo_to_google_photos(file_path, album_id, access_token, is_shared=False):
    """ Uploads photo and adds it to an album (shared or private) """
    
    # 1. Get upload token
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream"
    }

    with open(file_path, "rb") as f:
        photo_data = f.read()

    response = requests.post(upload_url, data=photo_data, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to upload {file_path}. Response: {response.text}")
        return
    
    upload_token = response.text.strip()

    # 2. Create media item
    filename = os.path.basename(file_path)
    media_url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    headers["Content-Type"] = "application/json"

    payload = {
        "newMediaItems": [
            {
                "description": filename,
                "simpleMediaItem": {
                    "fileName": filename,
                    "uploadToken": upload_token
                }
            }
        ]
    }

    response = requests.post(media_url, json=payload, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to create media item for {filename}. Response: {response.text}")
        return
    
    media_item_id = response.json()["newMediaItemResults"][0]["mediaItem"]["id"]

    # 3. Add to album (use correct endpoint for shared albums)
    if is_shared:
        album_url = f"https://photoslibrary.googleapis.com/v1/sharedAlbums/{album_id}:batchAddMediaItems"
    else:
        album_url = f"https://photoslibrary.googleapis.com/v1/albums/{album_id}:batchAddMediaItems"

    payload = {"mediaItemIds": [media_item_id]}
    response = requests.post(album_url, json=payload, headers=headers)

    if response.status_code == 200:
        move_photo_to_archive(file_path)
        logger.info(f"Successfully added {filename} to {'shared' if is_shared else 'private'} album {album_id}")
    else:
        move_photo_to_error_folder(file_path)
        logger.error(f"Failed to add {filename} to album. Response: {response.text}")
def move_photo_to_error_folder(file_path):
    errored_file_path = os.path.join(ERROR_FOLDER_PATH, os.path.basename(file_path))
    os.rename(file_path, errored_file_path)
    logger.info(f"Moved {file_path} to error folder.")
    print(f"Moved {file_path} to error folder.")

# Function to move the photo to the archive folder
def move_photo_to_archive(file_path):
    archive_file_path = os.path.join(ARCHIVE_FOLDER_PATH, os.path.basename(file_path))
    os.rename(file_path, archive_file_path)
    logger.info(f"Moved {file_path} to archive folder.")

# Function to count image files in a directory
def count_files_in_directory(directory):
    return sum(1 for item in os.listdir(directory) if os.path.isfile(os.path.join(directory, item)) and item.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')))

def sync_photos_to_google_photos(local_photos_folder_path):
    credentials_path = CREDENTIAL_FILE
    scopes = [
        "https://www.googleapis.com/auth/photoslibrary.appendonly",
        "https://www.googleapis.com/auth/photoslibrary.readonly",
        "https://www.googleapis.com/auth/photoslibrary.sharing"
    ]
    
    access_token = get_access_token(credentials_path, scopes)

    existing_album = get_album_by_title(access_token, ALBUM_NAME)
    if existing_album:
        album_id = existing_album['id']
        is_shared = "shareInfo" in existing_album  # If album has shareInfo, it's shared
        print(f"Album '{ALBUM_NAME}' found with ID: {album_id} (Shared: {is_shared})")
    else:
        album_id = create_album(access_token, ALBUM_NAME)
        if album_id is None:
            return
        is_shared = False  # New album is not shared by default
    
    total_files = count_files_in_directory(local_photos_folder_path)
    uploaded_count = 0

    for filename in os.listdir(local_photos_folder_path):
        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
            file_path = os.path.join(local_photos_folder_path, filename)
            upload_photo_to_google_photos(file_path, album_id, access_token, is_shared)
            uploaded_count += 1
            print(f"Uploaded {uploaded_count}/{total_files} files to Google Photos.")

    logger.info(f"Successfully completed upload to Google Photos for '{ALBUM_NAME}'")
    
    #delete_token_file()
# Entry point
def main():
    try:
        create_local_folders()
        sync_photos_to_google_photos(LOCAL_PHOTOS_FOLDER_PATH)
    except Exception as e:
        logger.error(f"An error occurred: {traceback.format_exc()}")

if __name__ == "__main__":
    main()