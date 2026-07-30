# AEA CORE — Developer Journal
Version 0.1
Project Name: Affiliate Employee AI (AEA Core)
Owner: Enock Hape

## Vision
Kutengeneza AI Employee anayefanya Affiliate Marketing kwa kujitegemea.

Hatua za mwanzo:
- Digistore24
- Pinterest

Baadaye:
- Upwork
- Fiverr
- ClickBank
- Impact
- CJ Affiliate
- Amazon Associates
- TikTok
- LinkedIn
- YouTube
- X (Twitter)

## Architecture
- Backend: FastAPI
- Language: Python 3.12
- Database: Supabase PostgreSQL
- Development: GitHub + GitHub Codespaces
- Version Control: Git
- Repository: hapeenooo888-tech/aea-core
- Supabase Project: Affiliate-employee-ai
- Project URL: https://zzqtwebtujrvuywqhclx.supabase.co

## Database Tables
- users (id, full_name, email, phone, country, language, created_at)
- missions (id, title, goal, status, created_at)
- workers (id, name, role, status, created_at)
- ai_memory (id, category, content, created_at)

## Folder Structure
AEA-CORE/
├── backend/
│   ├── app/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── main.py
│   ├── .env
│   └── requirements.txt
├── database/
├── deployment/
├── docs/
├── frontend/
├── prompts/
├── scripts/
├── tests/
├── workers/
└── README.md

## Environment Variables
- SUPABASE_URL
- SUPABASE_ANON_KEY

## Git Ignore
.env
__pycache__/
*.pyc
.vscode/
*.log

## Sprint 1 - Completed
- GitHub Repository
- GitHub Codespaces
- FastAPI
- API Running
- Supabase Project
- SQL Tables
- Folder Structure
- Environment File
- Git Ignore

## API Test
Endpoint: /
Response: {"message":"AEA Core API is running"}

## Challenges Faced
- SQL Error (extra bracket) → Fixed
- RLS Warning → Decided to use RLS
- python-dotenv not found → Fixed by adding to requirements.txt
- Invalid HTTP Request → Not a project bug
- Server stopped → Restarted with uvicorn

## Ongoing Work
Sprint 2: Connect Supabase (config.py, database.py, main.py, Supabase Client, Workers Endpoint)

## Roadmap
Sprint 3: Identity Vault
Sprint 4: Atlas CEO AI
Sprint 5: Digistore Worker
Sprint 6: Pinterest Worker
Sprint 7: Mission Engine
Sprint 8: Analytics Dashboard
Sprint 9: Autonomous Decision Engine
Sprint 10: Affiliate Employee AI Version 1.0

## Final Goal
Kuwa na AI Employee anayefanya kazi masaa 24/7:
- Kutafuta bidhaa za affiliate
- Kutengeneza Pins
- Kuchapisha Pinterest
- Kufuatilia clicks
- Kufuatilia commissions
- Kutengeneza reports
- Kukuomba uthibitisho pale tu inapohitajika (KYC au CAPTCHA)
