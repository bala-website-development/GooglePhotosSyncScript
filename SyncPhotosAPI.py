import os
import json
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from config import *

# Function to create the local folders if they don't exist
def create_local_folders():
    if not os.path.exists(LOCAL_PHOTOS_FOLDER_PATH):
        os.makedirs(LOCAL_PHOTOS_FOLDER_PATH)
    if not os.path.exists(ARCHIVE_FOLDER_PATH):
        os.makedirs(ARCHIVE_FOLDER_PATH)
    if not os.path.exists(ERROR_FOLDER_PATH):
        os.makedirs(ERROR_FOLDER_PATH)

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


# Function to get album details by title
def get_album_by_title(access_token, ALBUM_NAME):
    url = f"https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        albums = response.json().get("albums", [])
        for album in albums:
            if album["title"] == ALBUM_NAME:
                print(f"Album '{ALBUM_NAME}' already exists with ID: {album['id']}")
                return album
    else:
        print(f"Failed to get albums list. Error code: {response.status_code}")
    return None


# Function to create a new album
def create_album(access_token, ALBUM_NAME):

    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}", "Content-type": "application/json"}
    payload = {
        "album": {"title": ALBUM_NAME}
    }

    response = requests.post(url, data=json.dumps(payload), headers=headers)
    if response.status_code == 200:
        album_id = response.json()["id"]
        print(f"Album '{ALBUM_NAME}' created with ID: {album_id}")
        return album_id
    else:
        print(f"Failed to create the album '{ALBUM_NAME}'.")
        return None

# Function to upload a photo to Google Photos
def upload_photo_to_google_photos(file_path, album_id, access_token):
    url = f"https://photoslibrary.googleapis.com/v1/uploads"
    headers = {"Authorization": f"Bearer {access_token}", "Content-type": "application/octet-stream"}
    
    with open(file_path, "rb") as f:
        photo_data = f.read()
        
    response = requests.post(url, data=photo_data, headers=headers)
    upload_token = response.text.strip()

    if response.status_code == 200:
        filename = os.path.basename(file_path)

        # Prepare the request body
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

        url = f"https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
        headers["Content-type"] = "application/json"
        response = requests.post(url, data=json.dumps(payload), headers=headers)

        if response.status_code == 200:
            response_data = response.json()
            media_item_id = response_data["newMediaItemResults"][0]["mediaItem"]["id"]
            print(f"Uploaded {filename} to Google Photos.")
            #print(f" Media Item ID: {media_item_id}")
            url = f"https://photoslibrary.googleapis.com/v1/albums/{album_id}:batchAddMediaItems"
            payload = {"mediaItemIds": [media_item_id]}
            response = requests.post(url, data=json.dumps(payload), headers=headers)

            if response.status_code == 200:
                #print(f"Added {filename} to the album.")
                move_photo_to_archive(file_path)
            else:
                print(f"Failed to add {filename} to the album.")
                move_photo_to_error_folder(file_path)

        else:
            print(f"Failed to upload {filename} to Google Photos.")
    else:
        print(f"Failed to get upload token for {filename}.")


# Function to move the photo to the error folder
def move_photo_to_error_folder(file_path):
    filename = os.path.basename(file_path)
    errored_file_path = os.path.join(ERROR_FOLDER_PATH, filename)
    os.rename(file_path, errored_file_path)
    print(f"Moved {filename} to the error folder.")



# Function to move the photo to the archive folder
def move_photo_to_archive(file_path):
    filename = os.path.basename(file_path)
    archive_file_path = os.path.join(ARCHIVE_FOLDER_PATH, filename)
    os.rename(file_path, archive_file_path)
    print(f"Moved {filename} to the archive folder.")

#Function to remove the token file once the upload is done
def delete_token_file():
    if os.path.exists('token.json'):
        os.remove('token.json')


# Main function to sync photos to Google Photos
def sync_photos_to_google_photos(local_photos_folder_path):

    create_local_folders()

    credentials_path = CREDENTIAL_FILE
    scopes = ["https://www.googleapis.com/auth/photoslibrary"]
    
    # Get the access token
    access_token = get_access_token(credentials_path, scopes)

    # Check for existing album
    existing_album = get_album_by_title(access_token, ALBUM_NAME)
    if existing_album:
        album_id = existing_album['id']
        #print(f"Album '{ALBUM_NAME}' already exists with ID: {album_id}")
    else:
        # Create a new album
        album_id = create_album(access_token, ALBUM_NAME)
        if album_id is None:
            return

    for filename in os.listdir(local_photos_folder_path):
        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
            file_path = os.path.join(local_photos_folder_path, filename)
            upload_photo_to_google_photos(file_path, album_id, access_token)
            
    
    delete_token_file()


def main():
    sync_photos_to_google_photos(LOCAL_PHOTOS_FOLDER_PATH)

if __name__ == "__main__":
    main()
