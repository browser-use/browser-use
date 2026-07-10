# Publishing this reproducibility package to GitHub

The manuscript cites:

`https://github.com/zhangyouhao215-droid/pricai2026-navigator-cadence`

Create and populate that repository once before submission:

```powershell
# 1. Create an empty repo on GitHub (web UI or gh cli):
#    gh repo create zhangyouhao215-droid/pricai2026-navigator-cadence --public

# 2. Clone it locally
git clone https://github.com/zhangyouhao215-droid/pricai2026-navigator-cadence.git
cd pricai2026-navigator-cadence

# 3. Copy reproducibility materials from browser-use (adjust BROWSER_USE_ROOT)
$root = "D:\AI_Agent_Ali\browser-use"
Copy-Item "$root\paper\pricai2026\reproducibility\README.md" .\README.md
New-Item -ItemType Directory -Force -Path code, data, paper | Out-Null
Copy-Item "$root\browser_use\experiments\daily_task_eval" .\code\ -Recurse
Copy-Item "$root\scripts\compute_paper_stats.py" .\code\
Copy-Item "$root\scripts\compute_milestone_metrics.py" .\code\
Copy-Item "$root\paper\pricai2026\make_figures.py" .\code\
Copy-Item "$root\examples\evaluation\fixtures\task_cards.json" .\data\
Copy-Item "$root\paper\pricai2026\tables" .\paper\ -Recurse
Copy-Item "$root\paper\pricai2026\figures" .\paper\ -Recurse
Copy-Item "$root\paper\pricai2026\main.tex" .\paper\
Copy-Item "$root\paper\pricai2026\references.bib" .\paper\
# Copy run artifacts when available:
# Copy-Item "$root\tmp\daily_task_eval\*" .\data\

git add .
git commit -m "Initial reproducibility release for PRICAI 2026 navigator cadence study"
git push -u origin main
```

Verify the link resolves before submitting the camera-ready PDF.
