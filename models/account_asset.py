from odoo import fields, models


class AccountAsset(models.Model):
    _inherit = "account.asset"

    tha_transfer_date = fields.Date(
        string="Last Transfer Date",
        readonly=True,
        copy=False,
    )
