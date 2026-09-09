{
    "name": "Asset Department Transfer",
    "version": "1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Transfer a running asset to another department without touching posted depreciation",
    "description": """
Add a Transfer action on the Modify Asset wizard (Dispose / Sell /
Re-evaluate / Pause).

Transfer updates:
- account.asset.department_info
- account.asset.analytic_distribution
- analytic distribution on draft depreciation entries whose date is
  on or after the transfer date

Posted depreciation entries are never modified. No GL / NBV reclass
is posted. Gross-increase child assets in Running or Paused follow
the parent.
    """,
    "author": "THA",
    "license": "LGPL-3",
    "depends": ["account_asset"],
    "data": [
        "views/asset_modify_views.xml",
    ],
    "installable": True,
    "application": False,
}
