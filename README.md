# Hierarchical Vision — Django edition

A Django rewrite of [abyshergill/Hierarchical_Vision](https://github.com/abyshergill/Hierarchical_Vision)
(Flask org-chart viewer) extended with role-based access, rich profiles, a Google-style employee
directory and a full leave-management workflow.

## Quick start

**Windows (PowerShell)**
```powershell
cd hierarchical_vision_django
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then edit SECRET_KEY
```
**macOS / Linux**
```bash
cd hierarchical_vision_django
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then edit SECRET_KEY
```
**Then (all platforms)**
```bash
python manage.py migrate              # migrations are committed; run makemigrations only after changing a model
python manage.py test                 # all tests should pass
python manage.py createsuperuser      # Employee ID, email, full name, password -> Admin role
python manage.py backfill_leave_days  # only if you already had leave requests made before this version (optional)
python manage.py seed_demo            # optional demo people / leaves / holidays
python manage.py runserver            # http://127.0.0.1:8000
```
`seed_demo` users (password `ChangeMe!2026`): `EMP-001` Admin, `EMP-100`/`EMP-200` Managers, `EMP-101`/`EMP-102`/`EMP-201` Employees.

## What's new in this version
| Area | Change |
|---|---|
| **Overtime (OT)** | *Overtime* in the top bar: employees request OT (date, from/to time, reason; hours are calculated on the server, max `OT_MAX_HOURS_PER_DAY`, no overlap with other OT or with their own leave). The manager above them (or an Admin) approves/rejects under *Team leaves → Pending OT requests*; the employee is notified. Pending OT can be cancelled by its owner; OT shows in the profile *Leaves* tab and the CSV export. |
| **Alternate employee** | Every leave request must name an **alternate employee** (not yourself, active, and not on leave on those days). Managers see it when approving, it is in the CSV export, and the alternate is notified once the leave is approved. |
| **Safety** | The last active Admin cannot be demoted/deactivated; leave submission re-checks the balance inside a transaction; invalid review decisions return 400; review/cancel run under row locks. |
| **Leave** | Employees set a **from / to time for every working day** of a request. An Admin-defined **maximum hours per day** (`/leaves/policy/`, optional override per leave type) is enforced on the server. Weekends/holidays are skipped. Per-day detail is shown to managers and included in the CSV export. |
| **Salary privacy** | The Salary tab is visible **only to Admins and the account owner** - managers (even the direct manager) cannot see it, not even via `?tab=salary`. |
| **Search page** | Minimal: logo + search box only. |
| **Notifications** | Admin menu → *Send notification*: push to everyone, all managers, all employees or hand-picked accounts (optional e-mail, history kept). Also available as a bulk action in Django admin → Users. |
| **Newsletter groups** | Right-hand sidebar on every newsletter page with **Groups** and **Pinned**. Admins create department groups (*sidebar → + New*) and assign a **manager**. Only Admins, the manager and people they approve can read, post (text + pictures) and comment; everyone else sees a lock page and sends an **access request** that the manager/Admin approves or declines (*group → People*). Group posts, comments and pictures are never shown to non-members (server-side checks on pages, comments and `/media/`). |
| **Holiday PDF** | *Holidays → Download PDF* (`/leaves/holidays/download.pdf?year=2027`). English + Thai text, A4, repeating header row, page numbers. Needs `reportlab` (in requirements). |
| **Edit profile** | Redesigned page with a **live preview** (cover, avatar, name, contact, description) and per-picture undo / remove. |
| **Uploads** | Only **.jpg / .jpeg / .png**, **max 20 MB** (`MAX_IMAGE_UPLOAD_MB`). Checked in the browser *and* on the server by decoding the bytes (a renamed GIF/WebP/SVG/PHP file is refused), then re-encoded - EXIF/GPS and hidden payloads are removed, the file gets a random name. |
| **Newsletter** | `/newsletter/` - text + images, readable by every signed-in user. Admins publish, pin and manage everything; Admins choose which managers/employees may publish (*Admin → Newsletter publishers*); publishers manage only their own posts. |
| **UI** | New design system with **Light / Dark / Auto** (button in the top bar and in the user menu; remembered per browser). Org chart supports dark mode too. Grouped Admin menu, active-link highlight, cleaner cards and forms. |
| **Database** | SQLite by default; PostgreSQL is one environment variable away (see below). |

## Switching to PostgreSQL
Keep developing on SQLite - nothing changes. When you want PostgreSQL:

1. Install the driver and create an empty database/user (or run `docker compose -f docker-compose.postgres.yml up -d`):
   ```bash
   pip install -r requirements-postgres.txt
   ```
2. **(Existing data only)** while still on SQLite, export it:
   ```bash
   python manage.py dumpdata --natural-foreign --natural-primary \
       -e contenttypes -e auth.permission -e sessions --indent 2 -o data.json
   ```
3. Point the app at PostgreSQL in `.env` (see `.env.example`):
   ```
   DB_ENGINE=postgres
   DB_NAME=hierarchical_vision
   DB_USER=hv
   DB_PASSWORD=change-me
   DB_HOST=localhost
   DB_PORT=5432
   ```
   (or `DATABASE_URL=postgres://hv:change-me@localhost:5432/hierarchical_vision`)
4. Create the tables, then load the data:
   ```bash
   python manage.py migrate
   python manage.py loaddata data.json        # skip for a fresh install
   ```
5. Switch back any time by removing `DB_ENGINE` (or setting `DB_ENGINE=sqlite`). The two databases are independent copies.

`python manage.py test` uses whichever engine is configured (PostgreSQL needs permission to create a `test_...` database).
Uploaded images live in `media/` (not in the database) - copy that folder when you move servers.

## Feature map
| Requirement | Where |
|---|---|
| Custom user model, own credentials | `accounts/models.py` (`User`, `Role`), login by ID or email (`accounts/backends.py`) |
| Profile fields (picture, name, email, contact, description, position, background, peer/reporting manager) | `User` model |
| Employees edit only contact, description, picture, background | `ProfileSelfForm` + `profile_edit` view (all other fields are not in the form) |
| 3 profile tabs: User information / Leaves / Salary ("In Progress") | `templates/accounts/profile.html`, `_tab_*.html` |
| Google-style landing search, name or Employee ID, live suggestions | `accounts/home.html`, `search_employees()`, `/api/search/`, `static/js/app.js` |
| Card results → full profile | `search_results.html`, `_user_card.html` |
| Admin: create users, set hierarchy | `/manage/users/` (+ Django admin at `/django-admin/`) |
| Admin: define Standard Leaves | `/leaves/types/` (`LeaveType`) |
| Manager: team balances, holiday schedule, profiles, approve/reject, notified on requests | `/leaves/team/`, `leaves/services.py` |
| Employee: standard + hourly leave, notified on decision | `/leaves/apply/`, `notifications` app (in-app bell + e-mail) |
| Original org-chart (expand/collapse, branch colours, lineage highlight) | `/org-chart/` |
| Leave: per-day times + admin daily limit | `leaves/forms.py` (`LeaveApplicationForm`), `LeavePolicy`, `LeaveDay`, `/leaves/policy/` |
| Admin broadcast notifications | `/notifications/broadcast/` |
| Company newsletter + publisher permission | `newsletter/` app, `/newsletter/`, `/newsletter/publishers/` |
| Light / Dark / Auto UI | `static/css/app.css`, `static/js/theme.js` |

## Design decisions / assumptions
* **Role is the source of truth**: `Admin` ⇒ Django superuser/staff flags set automatically.
* **Hierarchy**: `User.manager` ("Peer / Reporting manager"). Cycles are rejected. A manager sees everyone *below* them recursively.
* **Who can see the Leaves tab**: the person, Admins, and anyone above them in the chain. **Salary tab: Admins and the owner only.** Everyone signed in can see the *User information* tab.
* **Who approves**: the nearest Manager/Admin above the applicant gets the notification; any Manager above them in the chain (or any Admin) may decide. Nobody can review their own request. If no manager exists, all other Admins are notified.
* **Balances** = standard quota (or a per-person override in `LeaveEntitlement`) − approved − pending. Stored internally in hours (`WORK_HOURS_PER_DAY = 8`), shown in days and hours.
* **Working days**: Mon–Fri (`WORKING_WEEKDAYS` in settings; use `(0,1,2,3,4,5)` for Mon–Sat). Weekends and published holidays are not deducted. One application cannot span two calendar years.
* **Leave time**: every working day has its own from/to time, capped by the Admin's *maximum hours per day* (leave policy, optionally overridden per leave type). Leave types without “allow partial days” must be taken as full days (= the daily limit). Windows may not overlap other pending/approved leave.
* **Notifications**: in-app (bell) plus e-mail. Default e-mail backend prints to the console; configure SMTP in `.env`.
* Login is required everywhere (company directory).
* Salary tab is a placeholder (access rules are already enforced).

## Security
| Threat | Protection |
|---|---|
| **CSRF** | `CsrfViewMiddleware` + `{% csrf_token %}` on every POST form (incl. logout, review, cancel); `SameSite=Lax` cookies; tested with `enforce_csrf_checks`. |
| **Brute force / credential stuffing** | Lock-out after 5 failed logins per account+IP and 30 per IP for 15 min (`accounts/throttle.py`, configurable in `.env`). Enforced inside the auth backend, so it also covers `/django-admin/`. Unknown IDs are throttled and timing-equalised (no user enumeration). 10+ char passwords with Django's common/numeric/similarity validators; PBKDF2 hashing. |
| **Scraping the directory** | Per-user rate limit (120 req/min) on search and the suggestion API. |
| **XSS** | Django auto-escaping; JS builds DOM with `textContent`; strict CSP (`script-src 'self'`, no inline scripts); Employee ID restricted to `[A-Za-z0-9_-]`. |
| **Clickjacking / sniffing** | `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP. |
| **Broken access control / IDOR** | Server-side checks on every view: role mixins, hierarchy checks for Leaves/Salary tabs, review and cancel; notifications only open for their recipient; employees can only post the 4 allowed profile fields. |
| **Malicious uploads** | Content-based JPEG/PNG check with Pillow (extension and MIME type are not trusted), allow-list `.jpg/.jpeg/.png` (**no GIF/WebP/SVG**), 20 MB / 8000 px / 50 MP caps, re-encode that strips metadata and appended payloads, random filenames, private-group pictures served only to group members through the `protected_media` view. |
| **Open redirect** | `next` parameters validated with `url_has_allowed_host_and_scheme`. |
| **SQL injection** | ORM only, no raw SQL. |
| **Session / transport** | HttpOnly + Secure cookies, 8 h sessions, session rotation on login, HTTPS redirect + HSTS when `DEBUG=0`; sensitive pages sent with `Cache-Control: no-store`. |
| **Mail header injection** | Notification titles are stripped of newlines. |
| **Secrets / config** | `SECRET_KEY` from env (app refuses to start with the dev key when `DEBUG=0`); configurable admin URL. |

**Before going live:** set `DEBUG=0`, a real `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `ADMIN_URL`, put it behind HTTPS
(set `BEHIND_PROXY=1` if a proxy terminates TLS), use a shared cache (Redis) if you run several workers, a real database
(PostgreSQL), SMTP for e-mail, and run `python manage.py check --deploy`. Keep dependencies updated (`pip list --outdated`).
Not included: 2-factor authentication and image re-encoding - good next steps.


## Public pages, support and comments

Search, the organization chart and newsletter are accessible without signing in. They disclose names, employee IDs, positions, reporting lines, profile pictures, and newsletter content (including comments) to anyone who can reach the site. Review this exposure before deploying on a public network; use a corporate network or access gateway if needed. Employee profile details, leave records, support requests and chart contact details remain authenticated. Only admins can see and update support requests; signed-in users can submit them. Comments are public but only signed-in users can post. Admins and comment authors can delete comments.

For privacy, **do not serve the media directory directly** through nginx, a CDN or cloud storage. Route `/media/` through Django's `protected_media` view: it permits anonymous access only to an active employee's current profile picture and images attached to newsletter posts. Other media requires login. Limit external access to this application and use HTTPS.

Run `python manage.py makemigrations accounts leaves notifications newsletter support` and `python manage.py migrate` before starting the updated application. Back up the database and media first; keep previously generated migration files when updating an existing installation.


## Newsletter groups, uploads and PDF - deployment notes
* **New tables** (`NewsGroup`, `GroupMembership`, `GroupAccessRequest`, `Post.group`) and changed image validators: run `python manage.py makemigrations accounts newsletter` then `migrate`.
* Pictures already stored as GIF/WebP keep working; only *new* uploads follow the JPG/JPEG/PNG rule.
* A post may carry up to `NEWSLETTER_MAX_IMAGES` (6) pictures of 20 MB each, so one request can reach ~120 MB. Set the reverse-proxy limit to match (nginx: `client_max_body_size 125m;`) or lower `NEWSLETTER_MAX_IMAGES` / `MAX_IMAGE_UPLOAD_MB`.
* Keep routing `/media/` through Django (`protected_media`). Serving the media folder straight from nginx/CDN would expose private-group pictures to anybody who has the URL.
* The PDF bundles Noto Sans / Noto Sans Thai (SIL OFL) in `leaves/fonts/`; deploy that folder with the code.
