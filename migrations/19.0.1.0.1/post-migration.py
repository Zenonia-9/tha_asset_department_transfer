import re
from datetime import date

from lxml import html

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    messages = env["mail.message"].search([
        ("model", "=", "account.asset"),
        ("subject", "=", "Department Transfer"),
    ])

    transfer_dates = {}
    for message in messages:
        try:
            asset_id = int(message.res_id)
        except (TypeError, ValueError):
            continue

        body_text = html.fromstring(message.body or "<div/>").text_content()
        match = re.search(r"Transfer date:\s*(\d{4}-\d{2}-\d{2})", body_text)
        if not match:
            continue

        try:
            transfer_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue

        transfer_dates[asset_id] = max(
            transfer_date,
            transfer_dates.get(asset_id, transfer_date),
        )

    for asset_id, transfer_date in transfer_dates.items():
        asset = env["account.asset"].browse(asset_id).exists()
        if asset and not asset.tha_transfer_date:
            asset.tha_transfer_date = transfer_date
