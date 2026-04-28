import os
import uuid
from supabase import create_client, Client

# Initialize the client only if keys are present
supabase: Client = None

def init_supabase():
    global supabase
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if url and key:
        supabase = create_client(url, key)

def upload_file(file_content: bytes, filename: str, content_type: str) -> str:
    """
    Uploads a file to the 'crisis-media' bucket.
    Returns the public URL of the uploaded file, or None if failed.
    """
    if not supabase:
        init_supabase()
    
    if not supabase:
        print("[storage] Supabase URL/Key missing in .env")
        return None

    bucket_name = "crisis-media"
    
    # Generate unique filename to prevent overwrites
    ext = filename.split('.')[-1] if '.' in filename else ''
    unique_filename = f"{uuid.uuid4().hex}.{ext}"

    try:
        # Upload the file
        res = supabase.storage.from_(bucket_name).upload(
            file=file_content,
            path=unique_filename,
            file_options={"content-type": content_type}
        )
        
        # Get public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(unique_filename)
        return public_url
    except Exception as e:
        print(f"[storage] Upload failed: {e}")
        return None
