# -*- coding: utf-8 -*-

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.fields import Command


TRANSFERABLE_STATES = ("open", "paused", "running")
MOVE_RELATION_FIELDS = (
    "depreciation_move_ids",
    "move_ids",
    "account_move_ids",
)
CHILD_RELATION_FIELDS = ("children_ids", "child_ids")


class AssetModify(models.TransientModel):
    _inherit = "asset.modify"

    modify_action = fields.Selection(
        selection_add=[("transfer", "Transfer")],
        ondelete={"transfer": "cascade"},
    )
    current_department_display = fields.Char(
        string="Current Department",
        compute="_compute_current_department_display",
    )
    dest_department_info = fields.Many2many(
        comodel_name="account.analytic.account",
        relation="asset_modify_dest_department_rel",
        column1="wizard_id",
        column2="analytic_account_id",
        string="Destination Department",
        help="Department the asset will belong to after the transfer.",
    )
    dest_analytic_distribution = fields.Json(
        string="New Analytic Distribution",
    )
    transfer_help = fields.Html(
        string="Transfer Help",
        compute="_compute_transfer_help",
    )

    @api.depends("asset_id")
    def _compute_current_department_display(self):
        for wizard in self:
            asset = wizard._get_asset()
            wizard.current_department_display = wizard._format_department_info(asset)

    @api.depends("date", "modify_action")
    def _compute_transfer_help(self):
        for wizard in self:
            date_label = wizard.date.strftime("%d/%m/%Y") if wizard.date else _("the transfer date")
            wizard.transfer_help = Markup(
                _(
                    "Posted depreciation stays on the previous department. "
                    "Draft entries on or after %s will use the new department "
                    "analytic distribution. No accounting reclass is posted. "
                    "The whole period of each updated draft entry is transferred."
                )
            ) % date_label

    @api.onchange("dest_department_info", "modify_action")
    def _onchange_dest_department_info(self):
        if self.modify_action != "transfer":
            return
        asset = self._get_asset()
        if not asset:
            return
        self.dest_analytic_distribution = self._build_dest_distribution(
            asset,
            self.dest_department_info,
        )

    def modify(self):
        self.ensure_one()
        if self.modify_action == "transfer":
            return self.action_transfer()
        return super().modify()

    def action_transfer(self):
        self.ensure_one()
        asset = self._get_asset()
        if not asset:
            raise UserError(_("No asset found for this transfer."))
        if asset.state not in TRANSFERABLE_STATES:
            raise UserError(
                _("Only running or paused assets can be transferred. This asset is in state '%s'.")
                % asset.state
            )
        dest_accounts = self._get_dest_analytic_accounts()
        if not dest_accounts:
            raise UserError(_("Select a destination department."))
        if self._departments_unchanged(asset, dest_accounts):
            raise UserError(_("Destination department must be different from the current department."))

        new_distribution = self.dest_analytic_distribution or self._build_dest_distribution(
            asset,
            dest_accounts,
        )
        transfer_date = self.date or fields.Date.context_today(self)
        assets = self._get_transfer_asset_set(asset)

        updated_moves = self.env["account.move"]
        for target in assets:
            self._write_asset_department(target, dest_accounts, new_distribution)
            draft_moves = self._get_transferable_draft_moves(target, transfer_date)
            self._apply_distribution_on_draft_moves(draft_moves, new_distribution)
            updated_moves |= draft_moves

        self._post_transfer_chatter(
            asset,
            assets,
            dest_accounts,
            transfer_date,
            updated_moves,
        )
        return {"type": "ir.actions.act_window_close"}

    def _get_asset(self):
        if "asset_id" in self._fields and self.asset_id:
            return self.asset_id
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model in ("account.asset", "account.asset.asset") and active_id:
            return self.env[active_model].browse(active_id)
        return self.env["account.asset"].browse()

    def _get_transfer_asset_set(self, asset):
        root = asset
        while "parent_id" in root._fields and root.parent_id:
            root = root.parent_id
        family = root
        for fname in CHILD_RELATION_FIELDS:
            if fname in root._fields:
                family |= root[fname]
                break
        transferable = family.filtered(
            lambda rec: rec.state in TRANSFERABLE_STATES or rec == asset
        )
        return transferable or asset

    def _get_dest_analytic_accounts(self):
        accounts = self.dest_department_info
        if accounts:
            return accounts
        distribution = self.dest_analytic_distribution or {}
        ids = [int(account_id) for account_id in distribution.keys() if str(account_id).isdigit()]
        return self.env["account.analytic.account"].browse(ids)

    def _departments_unchanged(self, asset, dest_accounts):
        current = self._get_asset_department_accounts(asset)
        if current:
            return set(current.ids) == set(dest_accounts.ids)
        current_ids = self._distribution_account_ids(asset.analytic_distribution or {})
        dest_ids = set(dest_accounts.ids)
        if current_ids and dest_ids and current_ids == dest_ids:
            return True
        return False

    def _get_asset_department_accounts(self, asset):
        if "department_info" not in asset._fields:
            return self.env["account.analytic.account"]
        value = asset.department_info
        if not value:
            return self.env["account.analytic.account"]
        field = asset._fields["department_info"]
        if field.type == "many2many" and field.comodel_name == "account.analytic.account":
            return value
        if field.type == "many2one" and field.comodel_name == "account.analytic.account":
            return value
        if field.type == "many2one" and "analytic_account_id" in value._fields:
            return value.analytic_account_id
        return self.env["account.analytic.account"]

    def _format_department_info(self, asset):
        if not asset:
            return ""
        if "department_info" in asset._fields and asset.department_info:
            value = asset.department_info
            if hasattr(value, "mapped"):
                names = value.mapped("display_name")
                return ", ".join(names)
            return str(value)
        distribution = asset.analytic_distribution or {}
        accounts = self.env["account.analytic.account"].browse(
            list(self._distribution_account_ids(distribution))
        )
        return ", ".join(accounts.mapped("display_name"))

    def _build_dest_distribution(self, asset, dest_accounts):
        dest_accounts = dest_accounts.filtered(lambda acc: acc.exists())
        current = dict(asset.analytic_distribution or {})
        if not dest_accounts:
            return current
        dest_plans = dest_accounts.mapped("plan_id") | dest_accounts.mapped("root_plan_id")
        kept = {}
        for key, percent in current.items():
            if not str(key).isdigit():
                kept[key] = percent
                continue
            account = self.env["account.analytic.account"].browse(int(key))
            account_plans = account.plan_id | account.root_plan_id
            if dest_plans and account_plans & dest_plans:
                continue
            kept[key] = percent
        share = 100.0 / float(len(dest_accounts))
        for account in dest_accounts:
            kept[str(account.id)] = share
        return kept

    def _write_asset_department(self, asset, dest_accounts, new_distribution):
        vals = {}
        if "analytic_distribution" in asset._fields:
            vals["analytic_distribution"] = new_distribution
        if "department_info" in asset._fields:
            field = asset._fields["department_info"]
            if field.type == "many2many" and field.comodel_name == "account.analytic.account":
                vals["department_info"] = [Command.set(dest_accounts.ids)]
            elif field.type == "many2one" and field.comodel_name == "account.analytic.account":
                vals["department_info"] = dest_accounts[:1].id
            elif field.type == "many2one" and field.comodel_name == "hr.department":
                department = self._match_hr_department(dest_accounts, asset)
                if department:
                    vals["department_info"] = department.id
        if vals:
            asset.write(vals)

    def _match_hr_department(self, dest_accounts, asset):
        if "hr.department" not in self.env:
            return False
        Department = self.env["hr.department"]
        domain_company = [("company_id", "in", [False, asset.company_id.id])]
        for account in dest_accounts:
            if "analytic_account_id" in Department._fields:
                match = Department.search(
                    [("analytic_account_id", "=", account.id)] + domain_company,
                    limit=1,
                )
                if match:
                    return match
            match = Department.search(
                [("name", "=", account.name)] + domain_company,
                limit=1,
            )
            if match:
                return match
        return Department.browse()

    def _get_asset_moves(self, asset):
        moves = self.env["account.move"]
        for fname in MOVE_RELATION_FIELDS:
            if fname in asset._fields:
                moves |= asset[fname]
        Move = self.env["account.move"]
        if "asset_id" in Move._fields:
            moves |= Move.search([("asset_id", "=", asset.id)])
        if "asset_ids" in Move._fields:
            moves |= Move.search([("asset_ids", "in", asset.ids)])
        return moves

    def _get_transferable_draft_moves(self, asset, transfer_date):
        return self._get_asset_moves(asset).filtered(
            lambda move: move.state == "draft" and move.date and move.date >= transfer_date
        )

    def _apply_distribution_on_draft_moves(self, moves, new_distribution):
        for move in moves:
            if move.state != "draft":
                continue
            lines = move.line_ids.filtered(
                lambda line: line.analytic_distribution or line.account_id.account_type in (
                    "expense",
                    "expense_direct_cost",
                    "expense_depreciation",
                )
            )
            if not lines:
                lines = move.line_ids.filtered(lambda line: line.debit)
            for line in lines:
                line.analytic_distribution = new_distribution

    def _distribution_account_ids(self, distribution):
        ids = set()
        for key in (distribution or {}):
            if str(key).isdigit():
                ids.add(int(key))
        return ids

    def _post_transfer_chatter(self, asset, assets, dest_accounts, transfer_date, updated_moves):
        dest_label = ", ".join(dest_accounts.mapped("display_name"))
        current_label = self._format_department_info(asset) or _("(empty)")
        note = self.name or ""
        body = Markup(
            "<p>%s</p><ul>"
            "<li>%s</li>"
            "<li>%s</li>"
            "<li>%s</li>"
            "<li>%s</li>"
            "%s</ul>"
        ) % (
            _("Asset transferred between departments."),
            _("From: %s") % current_label,
            _("To: %s") % dest_label,
            _("Transfer date: %s") % transfer_date,
            _("Draft depreciation entries updated: %s") % len(updated_moves),
            Markup("<li>%s</li>") % (_("Note: %s") % note) if note else Markup(""),
        )
        if len(assets) > 1:
            extra = _("Related assets updated: %s") % ", ".join(assets.mapped("name"))
            body += Markup("<p>%s</p>") % extra
        asset.message_post(body=body, subject=_("Department Transfer"))
        for related in assets - asset:
            related.message_post(body=body, subject=_("Department Transfer"))
