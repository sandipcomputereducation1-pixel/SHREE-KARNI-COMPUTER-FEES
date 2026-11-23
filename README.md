# Shree Karni Computer & Education – Fee Management

## Features
- Admin login
- Student registration, search, edit and archive
- Default courses: RSCIT, TALLY, DECE, LIBRARY, YOGA, BA, MA, BCA and PGDCA (fees editable in Courses)
- Course and fee setup
- Cash, UPI and Bank payment entries
- Multiple installments and due-fee tracking
- Individual student fee receipt after every payment (browser Print → Save as PDF), showing course, paid amount, total paid and remaining balance
- Dashboard, date-wise reports and CSV export
- SQLite database backup download

## Run locally (Windows)
1. Install Python 3.11 or newer.
2. Open Command Prompt in this folder.
3. Run:
   ```bash
   py -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   set ADMIN_USERNAME=admin
   set ADMIN_PASSWORD=YourStrongPassword123
   set SECRET_KEY=put-a-long-random-secret-here
   python app.py
   ```
4. Open http://127.0.0.1:5000

Default local login only if environment variables are not set:
- Username: `admin`
- Password: `ChangeMe@123`
**Change this immediately after first login.**

## Deploy on Render
1. Create a new GitHub repository and upload all files/folders, preserving the structure.
2. In Render choose **New → Web Service**, connect the repository.
3. Runtime: Python. Build command: `pip install -r requirements.txt`.
4. Start command: `gunicorn app:app`.
5. Add a persistent disk mounted at `/var/data` (1 GB).
6. Add environment variables:
   - `DATA_DIR` = `/var/data`
   - `SECRET_KEY` = a long random secret
   - `ADMIN_USERNAME` = your chosen admin username
   - `ADMIN_PASSWORD` = a strong unique password
7. Deploy. Open the service URL and log in.

## Important
- Do not publish your admin password or SECRET_KEY in GitHub.
- Keep the Render persistent disk attached; without persistent storage, local SQLite data can be lost during redeploy/restart.
- Download the database regularly using the **Backup** endpoint. Add a dashboard link to `/backup` after deployment if desired.
- UPI and Bank entries are manual records; this version does not automatically verify payments or connect to a bank.
- Receipts can be printed or saved as PDF from the browser.
- Use HTTPS in production (Render provides HTTPS).
