# PDF to Word server (with OCR)

Files:
- main.py          the server (the brain)
- static/index.html a simple test page served at the home address
- requirements.txt  Python libraries to install
- Dockerfile        recipe that builds the server plus OCR tools
- .dockerignore     files Docker should skip

## Deploy on Render (free tier)

1. Make a free GitHub account (github.com) if you don't have one.
2. Click "New repository", name it `pdf-to-word-server`, set it to Public, create it.
3. Click "uploading an existing file", drag in EVERYTHING from this folder
   (keep the `static` folder with index.html inside it), then "Commit changes".
4. Make a free account at render.com (sign in with GitHub is easiest).
5. New + -> Web Service -> connect your `pdf-to-word-server` repo.
6. Settings:
   - Language / Runtime: Docker (it finds the Dockerfile by itself)
   - Instance type: Free
7. Under Environment Variables add:  MAX_PAGES = 5   and   MAX_MB = 10
   (low limits stop the free server running out of memory)
8. Click Create Web Service and wait. The first build takes several minutes.
9. When it says "Live", open the URL Render gives you (like
   https://pdf-to-word-server.onrender.com). You'll see the test page.

## Test it

- A normal PDF: should finish in a few seconds. Status says "Done."
- A scanned PDF: slower. Status says "Done (scan read with OCR)."
- The first request after idle can take ~1 minute while the free server wakes up.

## If something fails

Open your service on Render -> Logs, copy the red error text, and send it to Claude.

## Settings you can change (Environment Variables)

MAX_MB     biggest upload in MB (default 15)
MAX_PAGES  most pages allowed (default 20)
OCR_LANG   OCR language, e.g. eng (needs the matching tesseract-ocr-xxx
           package added in the Dockerfile for languages other than English)
