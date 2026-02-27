#!/usr/bin/env python3
import os
import json
import re
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]
CHANNEL_ID     = os.environ.get("YOUTUBE_CHANNEL_ID", "")
PLAYLIST_ID    = os.environ.get("YOUTUBE_PLAYLIST_ID", "")
OUTPUT_FILE    = "videos.json"
MAX_RESULTS    = 200

creds = Credentials(
    token=None,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    scopes=["https://www.googleapis.com/auth/youtube.readonly"]
)
creds.refresh(Request())
youtube = build("youtube", "v3", credentials=creds)


def get_uploads_playlist_id(channel_id):
    res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = res.get("items", [])
    if not items:
        raise ValueError(f"チャンネルが見つかりません: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_video_ids_from_playlist(playlist_id):
    video_ids = []
    page_token = None
    while True:
        res = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token
        ).execute()
        for item in res.get("items", []):
            vid = item["contentDetails"].get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = res.get("nextPageToken")
        if not page_token or len(video_ids) >= MAX_RESULTS:
            break
    return video_ids[:MAX_RESULTS]


def extract_tags_from_description(description):
    tags = set()
    hashtags = re.findall(r'#(\S+)', description)
    tags.update(hashtags)
    tag_line = re.findall(r'(?:タグ|Tags?)[：:]\s*(.+)', description, re.IGNORECASE)
    for line in tag_line:
        for t in re.split(r'[,、\s]+', line):
            if t.strip():
                tags.add(t.strip())
    return sorted(tags)[:10]


def get_video_details(video_ids):
    videos = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        res = youtube.videos().list(part="snippet,status", id=",".join(chunk)).execute()
        for item in res.get("items", []):
            status = item.get("status", {})
            privacy = status.get("privacyStatus", "")
            if privacy not in ("public", "unlisted"):
                continue
            snippet = item.get("snippet", {})
            video_id = item["id"]
            thumbs = snippet.get("thumbnails", {})
            thumb = (
                thumbs.get("maxres", {}).get("url") or
                thumbs.get("high", {}).get("url") or
                thumbs.get("medium", {}).get("url") or
                f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
            )
            yt_tags = snippet.get("tags", [])
            desc_tags = extract_tags_from_description(snippet.get("description", ""))
            all_tags = list(dict.fromkeys(yt_tags + desc_tags))[:10]
            videos.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail": thumb,
                "tags": all_tags,
                "privacy": privacy,
            })
    return videos


def load_existing(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"videos": []}


def main():
    if PLAYLIST_ID:
        playlist_id = PLAYLIST_ID
        print(f"プレイリストから取得: {playlist_id}")
    elif CHANNEL_ID:
        playlist_id = get_uploads_playlist_id(CHANNEL_ID)
        print(f"チャンネルのuploadsから取得: {CHANNEL_ID}")
    else:
        raise ValueError("YOUTUBE_CHANNEL_ID か YOUTUBE_PLAYLIST_ID を設定してください")

    video_ids = get_video_ids_from_playlist(playlist_id)
    print(f"{len(video_ids)} 本の動画IDを取得")

    videos = get_video_details(video_ids)
    print(f"公開+限定公開: {len(videos)} 本")

    existing = load_existing(OUTPUT_FILE)
    existing_ids = {v["video_id"] for v in existing.get("videos", [])}
    new_ids = {v["video_id"] for v in videos}
    added = new_ids - existing_ids
    if added:
        print(f"新規追加: {len(added)} 本")
    else:
        print("変更なし")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": sorted(videos, key=lambda v: v["published_at"], reverse=True)
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ {OUTPUT_FILE} を更新しました（{len(videos)} 本）")


if __name__ == "__main__":
    main()
