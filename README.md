# VoteSpace

A Flask and SQLite voting system with public polls, results, and an admin dashboard.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Admin access

On the first run, the app creates an admin user:

- Username: `admin`
- Password: `admin123`

Change the `SECRET_KEY` environment variable and replace the default account before deploying.
