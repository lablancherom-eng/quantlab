QuantLab V5 — Oil addition (USO)

Replace these files in your GitHub repository:
- live.py (repository root)
- site/index.html
- site/app.js

You can also upload only live.py to add oil to the trading algorithm, but
USO will not appear as a separate quote card until you update the site files.

USO tracks daily changes related to WTI oil futures; it is NOT a WTI futures
contract or spot crude oil. There are four symbols in the scan.

Keep PAPER_AUTO_TRADE=false for observation. The prototype is not suitable
for unattended continuous trading on Render Free.

A public web deployment should consider Alpaca market-data redistribution rights.
