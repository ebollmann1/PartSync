from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    t14_location_id = fields.Char(
        string="Turn 14 Location ID", index=True, copy=False,
        help="Turn 14 source identifier; leading zeros are preserved.",
    )

    _t14_location_uniq = models.Constraint(
        "unique(company_id, t14_location_id)",
        "Turn 14 Location ID must be unique per company.",
    )
