YT AUTO BOT - CLEAN BUILD
=========================

This package is a corrected rebuild of the local bot.

INSTALL
-------
1. Extract/replace these files in E:\YT Auto Bot.
2. Keep your existing client_secret.json and youtube_token.json.
3. Keep FFmpeg at E:\ffmpeg\bin\ffmpeg.exe.
4. Ensure Deno is installed and on PATH:
   C:\Users\HP\.deno\bin\deno.exe
5. Install requirements:
   .\venv\Scripts\python.exe -m pip install -r requirements.txt

RUN
---
YouTube source:
   .\venv\Scripts\python.exe run_all.py "https://www.youtube.com/watch?v=VIDEO_ID"

Local source:
   .\venv\Scripts\python.exe run_all.py local

YOUTUBE DOWNLOAD FIX
--------------------
The downloader no longer relies on one fragile format expression. It tries:
1. YouTube combined MP4 format 18
2. HTTPS combined MP4
3. MP4 video + M4A audio
4. Best available format

It explicitly uses Deno, FFmpeg, no-playlist, force-overwrite and no-continue.
This addresses the YouTube client/SABR behavior encountered during testing.

UPLOAD POLICY
-------------
The newest Short in each upload batch is requested as PUBLIC immediately.
All earlier Shorts in that batch are uploaded PRIVATE with a publishAt time.
YouTube then automatically changes a scheduled video to PUBLIC at that time.

The scheduler also checks existing channel uploads on every run. If a bot-created
scheduled video has a publishAt time in the past but is still private, the bot
attempts to change it to PUBLIC.

IMPORTANT YOUTUBE API LIMITATION
--------------------------------
YouTube states that videos.insert uploads from unverified API projects created
after July 28, 2020 can be restricted to private until the API project passes
YouTube's audit. If that restriction applies to your Google Cloud project, the
code can request PUBLIC but YouTube may refuse/override it. The bot verifies the
actual privacy state after every upload and prints a warning if YouTube did not
make the newest video public.

OAUTH
-----
Keep client_secret.json in E:\YT Auto Bot.
The OAuth token is stored as youtube_token.json.

DUPLICATES
----------
temp\youtube_upload_log.json records uploaded output files so rerunning the
bot does not upload the same rendered Short again.

COPYRIGHT
---------
Only process and publish footage you own or are authorized/licensed to use.
