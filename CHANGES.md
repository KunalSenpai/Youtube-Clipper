# YT Auto Bot — Content Identification / SEO / Metadata Isolation Fixes

See the chat response for the full technical report (root causes, test
results, run instructions). Quick reference for what's in this folder:

- config.py              (unchanged from the previous update)
- main.py                (download_youtube() no longer writes a shared global
                           metadata file; clip_id added per clip)
- source_detector.py     (detect_video_source() takes source_metadata as an
                           explicit parameter; "hour"/duration noise-word
                           filtering; character-hallucination guard; URL
                           stripping)
- seo_generator.py       (URL-scrub safety net on title/description/tags)
- youtube_automator.py   (SRT caption filename now scoped per clip/run;
                           validate_before_upload() rejects any URL in
                           public metadata)
- _gitignore             (unchanged from the previous update)
- test_isolation.py      (regression test -- run with `python test_isolation.py`
                           from the project root; 21 checks, all passing)

## Install
Replace the corresponding files in E:\YT Auto Bot with these, then run:

    .\venv\Scripts\python.exe test_isolation.py

before doing a real run, to confirm the fixes hold on this machine too.
