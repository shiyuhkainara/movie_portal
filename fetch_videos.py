#!/usr/bin/env python3
"""
YouTube動画取得スクリプト
- チャンネルのuploadsプレイリスト または 特定プレイリストから動画を取得
- 公開（public）＋限定公開（unlisted）の動画を対象
- videos.json を自動更新

使い方:
  pip install google-api-python-client
  python fetch_videos.py

必要な環境変数:
  YOUTUBE_API_KEY   : YouTube Data API v3 キー
  YOUTUBE_CHANNEL_ID: チャンネルID（例: UCxxxxxxxxxxxxxxxxxx）
                      または
  YOUTUBE_PLAYLIST_ID: プレイリストID（例: PLxxxxxxxxxxxxxxxxxx）
                       ※どちらか一方を設定
"""

import os
import json
import re
from datetime import datetime, timezone
from googleapiclient.discovery import build

# ─── 設定 ───────────────────────────────────────────
API_KEY        = os.environ["YOUTUBE_API_KEY"]
CHANNEL_ID     = os.environ.get("YOUTUBE_CHANNEL_ID", "")
PLAYLIST_ID    = os.environ.get("YOUTUBE_PLAYLIST_ID", "")  # CHANNEL_IDより優先
OUTPUT_FILE    = "videos.json"
MAX_RESULTS    = 200  # 最大取得件数
# ─────────────────────────────────────────────────────

youtube = build("youtube", "v3", developerKey=API_KEY)


def get_uploads_playlist_id(channel_id: str) -> str:
    """チャンネルIDからuploadsプレイリストIDを取得"""
    res = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    ).execute()
    items = res.get("items", [])
    if not items:
        raise ValueError(f"チャンネルが見つかりません: {channel_id}")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_video_ids_from_playlist(playlist_id: str) -> list[str]:
    """プレイリストから全動画IDを取得"""
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


def extract_tags_from_description(description: str) -> list[str]:
    """
    動画説明文からタグを自動抽出。
    - #タグ 形式のハッシュタグ
    - 「タグ：xxx, yyy」のような明示的な記述
    """
    tags = set()
    # #ハッシュタグ
    hashtags = re.findall(r'#(\S+)', description)
    tags.update(hashtags)
    # 「タグ：」「Tags:」記述
    tag_line = re.findall(r'(?:タグ|Tags?)[：:]\s*(.+)', description, re.IGNORECASE)
    for line in tag_line:
        for t in re.split(r'[,、\s]+', line):
            if t.strip():
                tags.add(t.strip())
    return sorted(tags)[:10]  # 最大10個


def get_video_details(video_ids: list[str]) -> list[dict]:
    """動画の詳細情報を取得（公開＋限定公開のみ）"""
    videos = []
    # 50件ずつ分割してAPI呼び出し
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        res = youtube.videos().list(
            part="snippet,status",
            id=",".join(chunk)
        ).execute()
        for item in res.get("items", []):
            status = item.get("status", {})
            privacy = status.get("privacyStatus", "")
            # public または unlisted のみ対象（private は除外）
            if privacy not in ("public", "unlisted"):
                continue
            snippet = item.get("snippet", {})
            video_id = item["id"]
            title = snippet.get("title", "")
            published_at = snippet.get("publishedAt", "")
            description = snippet.get("description", "")
            # サムネイル（高画質優先）
            thumbs = snippet.get("thumbnails", {})
            thumb = (
                thumbs.get("maxres", {}).get("url") or
                thumbs.get("high", {}).get("url") or
                thumbs.get("medium", {}).get("url") or
                f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
            )
            # タグ：YouTube公式タグ ＋ 説明文からの抽出
            yt_tags = snippet.get("tags", [])
            desc_tags = extract_tags_from_description(description)
            all_tags = list(dict.fromkeys(yt_tags + desc_tags))[:10]

            videos.append({
                "video_id": video_id,
                "title": title,
                "published_at": published_at,
                "thumbnail": thumb,
                "tags": all_tags,
                "privacy": privacy,
            })
    return videos


def load_existing(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"videos": []}


def save(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {path} を更新しました（{len(data['videos'])} 本）")


def main():
    # 対象プレイリストIDを決定
    if PLAYLIST_ID:
        playlist_id = PLAYLIST_ID
        print(f"🎬 プレイリストから取得: {playlist_id}")
    elif CHANNEL_ID:
        playlist_id = get_uploads_playlist_id(CHANNEL_ID)
        print(f"📺 チャンネルのuploadsから取得: {CHANNEL_ID} → {playlist_id}")
    else:
        raise ValueError("YOUTUBE_CHANNEL_ID か YOUTUBE_PLAYLIST_ID を環境変数に設定してください")

    # 動画ID一覧取得
    video_ids = get_video_ids_from_playlist(playlist_id)
    print(f"  {len(video_ids)} 本の動画IDを取得")

    # 詳細取得
    videos = get_video_details(video_ids)
    print(f"  公開+限定公開: {len(videos)} 本")

    # 既存データと差分確認
    existing = load_existing(OUTPUT_FILE)
    existing_ids = {v["video_id"] for v in existing.get("videos", [])}
    new_ids = {v["video_id"] for v in videos}
    added = new_ids - existing_ids
    if added:
        print(f"  🆕 新規追加: {len(added)} 本 → {added}")
    else:
        print("  変更なし")

    # 保存
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": sorted(videos, key=lambda v: v["published_at"], reverse=True)
    }
    save(OUTPUT_FILE, output)


if __name__ == "__main__":
    main()
