# Asset Department Transfer

## Overview
Extends the Odoo `account_asset` module to allow transferring a running asset to another department without modifying already-posted depreciation entries. Adds a Transfer action to the existing Modify Asset wizard.

## Features
- Transfer action added to the Modify Asset wizard (alongside Dispose / Sell / Re-evaluate / Pause)
- Updates the asset's department info (`account.asset.department_info`) on transfer
- Updates the asset's analytic distribution (`account.asset.analytic_distribution`)
- Updates analytic distribution on draft depreciation entries dated on or after the transfer date
- Posted depreciation entries are never modified
- No GL or NBV reclass journal entries are posted
- Gross-increase child assets in Running or Paused status automatically follow the parent asset's department

## Requirements
- Odoo 19
- Depends on: `account_asset`

## Installation
Install the module from Apps or update via command line:
```bash
docker exec odoo_19 odoo -d THA -u tha_asset_department_transfer --stop-after-init
```

## Usage
1. Open an asset that is in Running or Paused status
2. Click **Modify** to open the Modify Asset wizard
3. Select the **Transfer** action
4. Choose the target department and confirm
5. The asset's department and analytic distribution are updated; draft future depreciation entries reflect the new department

## Technical Details
### Wizard
- Extends `account.asset.modify` wizard to add the Transfer action type

### Views
- Inherits the existing asset modify wizard view to inject the Transfer option (`views/asset_modify_views.xml`)

### Behavior
- Only draft depreciation lines with a date >= the transfer date are updated
- Posted depreciation lines are left untouched to preserve accounting integrity
- Child assets created through gross-increase that are in Running or Paused status follow the parent's department change automatically

## Author
THA

## License
LGPL-3